"""Codex chat state and stdio transport for the terminal UI. No network listener."""
import copy
import json
import os
from pathlib import Path
import queue
import secrets
import subprocess
import threading
import time
from concurrent.futures import Future

from hub_config import AUTH_ENV, ROOT, VERSION, environment, executable, load

APPROVAL_MODES = {
    'ask': {'approvalPolicy': 'on-request', 'approvalsReviewer': 'user', 'sandboxPolicy': {'type': 'workspaceWrite'}},
    'auto': {'approvalPolicy': 'on-request', 'approvalsReviewer': 'auto_review', 'sandboxPolicy': {'type': 'workspaceWrite'}},
    'full': {'approvalPolicy': 'never', 'approvalsReviewer': 'user', 'sandboxPolicy': {'type': 'dangerFullAccess'}},
}

class Rpc:
    def __init__(self, slot, callback, root=ROOT):
        env = environment(slot, root)
        self.binary = executable(root)
        self.process = subprocess.Popen([self.binary, 'app-server', '--stdio'], env=env,
                                        stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=subprocess.DEVNULL)
        self.pending, self.counter = {}, 0
        self.lock = threading.Lock()
        self.events = queue.Queue()
        self.callback = callback
        self.reader = threading.Thread(target=self.read, daemon=True)
        self.reader.start()
        threading.Thread(target=self.dispatch, daemon=True).start()
        try:
            self.call('initialize', {'clientInfo': {'name': 'codex_hub', 'title': 'Codex Hub', 'version': VERSION},
                                     'capabilities': {'experimentalApi': True}})
            self.write({'method': 'initialized', 'params': {}})
        except Exception:
            self.close()
            raise

    def write(self, data):
        with self.lock:
            self.process.stdin.write((json.dumps(data) + '\n').encode())
            self.process.stdin.flush()

    def call(self, method, params=None):
        with self.lock:
            self.counter += 1
            ident = self.counter
            future = self.pending[ident] = Future()
        try:
            self.write({'id': ident, 'method': method, 'params': params or {}})
            return future.result(timeout=45)
        finally:
            with self.lock:
                self.pending.pop(ident, None)

    def read(self):
        try:
            for line in self.process.stdout:
                message = json.loads(line)
                if 'method' in message:
                    self.events.put(message)
                else:
                    with self.lock:
                        future = self.pending.get(message.get('id'))
                        if future and not future.done():
                            if 'error' in message:
                                future.set_exception(RuntimeError(message['error'].get('message', 'Codex request failed')))
                            else:
                                future.set_result(message.get('result', {}))
        finally:
            with self.lock:
                for future in self.pending.values():
                    if not future.done():
                        future.set_exception(RuntimeError('Codex connection closed. Reopen the hub.'))
            self.events.put({'method': 'hub/disconnected', 'params': {}})

    def dispatch(self):
        while True:
            message = self.events.get()
            try:
                self.callback(message)
            except Exception:
                # Preserve the reader and report the failed event rather than losing approvals.
                self.callback({'method': 'hub/eventError', 'params': {}})
            if message['method'] == 'hub/disconnected':
                return

    def close(self):
        if self.process.poll() is None:
            self.process.terminate()
        try:
            self.process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait()
        # Closing a process does not close its Python pipe objects. Wait for
        # the reader to consume EOF before releasing its stream.
        with self.lock:
            self.process.stdin.close()
        if threading.current_thread() is not self.reader:
            self.reader.join(timeout=3)
        self.process.stdout.close()


class Hub:
    def __init__(self, root=ROOT, factory=Rpc, state_file=None):
        self.root = root
        self.factory = (lambda slot, callback: Rpc(slot, callback, root)) if factory is Rpc else factory
        self.lock = threading.RLock()
        self.clients, self.views, self.active, self.requests, self.errors = {}, {}, {}, {}, {}
        self.revision = 0
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.file = state_file or root / 'tui-state' / 'session.json'
        self.file.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            self.saved = json.loads(self.file.read_text())
        except FileNotFoundError:
            self.saved = {'queues': {}, 'paused': {}, 'draft': {}}
        # A restart must not silently replay messages whose dispatch is uncertain.
        for key, pending in self.saved.get('queues', {}).items():
            if pending:
                self.saved.setdefault('paused', {})[key] = True

    def persist(self):
        temp = self.file.with_suffix('.tmp')
        with temp.open('w') as out:
            os.chmod(temp, 0o600)
            json.dump(self.saved, out)
        temp.replace(self.file)
        self.revision += 1


    def client(self, slot):
        if slot not in load(self.root)['accounts']:
            raise ValueError('Choose a configured account.')
        if slot not in self.clients:
            self.clients[slot] = self.factory(slot, lambda event: self.event(slot, event))
        return self.clients[slot]


    @staticmethod
    def key(slot, ident):
        return slot + ':' + ident


    def view(self, slot, ident):
        key = self.key(slot, ident)
        if key not in self.views:
            self.views[key] = self.client(slot).call('thread/read', {'threadId': ident, 'includeTurns': True})['thread']
        return self.views[key]


    def thread(self, slot, ident):
        with self.lock:
            view = self.view(slot, ident)
            key = self.key(slot, ident)
            if '_tokenUsage' not in view and key in self.saved.get('telemetry', {}):
                view['_tokenUsage'] = self.saved['telemetry'][key]
            settings = self.saved.get('settings', {}).get(key, {})
            for field in ('model', 'effort', 'approvalMode'):
                if settings.get(field):
                    view['_' + field] = settings[field]
            return {'thread': copy.deepcopy(view), 'active': self.active.get(key),
                    'queue': copy.deepcopy(self.saved.get('queues', {}).get(key, [])),
                    'paused': self.saved.get('paused', {}).get(key, False),
                    'error': self.errors.get(key),
                    'requests': [v for v in self.requests.values() if v['slot'] == slot and v['params'].get('threadId') == ident],
                    'revision': self.revision}


    def event(self, slot, message):
        with self.lock:
            method, p = message['method'], message.get('params') or {}
            ident = p.get('threadId')
            key = self.key(slot, ident) if ident else None
            self.revision += 1
            if 'id' in message:
                supported = ('item/commandExecution/requestApproval', 'item/fileChange/requestApproval',
                             'item/tool/requestUserInput', 'item/permissions/requestApproval')
                if method in supported:
                    self.requests[slot + ':' + str(message['id'])] = {**message, 'slot': slot}
                else:
                    self.clients[slot].write({'id': message['id'], 'error': {'code': -32601,
                        'message': 'This hub does not support this client request. Use the Codex CLI for this tool.'}})
                    if key:
                        self.errors[key] = 'A tool requested an unsupported interaction: ' + method
                return
            if method == 'hub/disconnected':
                for k in list(self.active):
                    if k.startswith(slot + ':'):
                        self.active.pop(k)
                        self.errors[k] = 'Connection lost. Queue paused; reopen the hub before continuing.'
                        self.saved.setdefault('paused', {})[k] = True
                self.persist()
                return
            if method == 'serverRequest/resolved':
                self.requests.pop(slot + ':' + str(p.get('requestId')), None)
            if not key or key not in self.views:
                return
            view = self.views[key]
            if method in ('turn/started', 'turn/completed'):
                turn = p['turn']
                turns = view.setdefault('turns', [])
                existing = next((t for t in turns if t['id'] == turn['id']), None)
                if existing:
                    old_items = existing.get('items', [])
                    existing.update(turn)
                    if not existing.get('items'):
                        existing['items'] = old_items
                else:
                    turns.append(turn)
                if method == 'turn/started':
                    self.active[key] = turn['id']
                else:
                    self.active.pop(key, None)
                    view['updatedAt'] = int(time.time())
                    for request_key, request in list(self.requests.items()):
                        if request['slot'] == slot and request['params'].get('turnId') == turn['id']:
                            self.requests.pop(request_key)
                    if turn.get('status') != 'completed':
                        self.saved.setdefault('paused', {})[key] = True
                        if turn.get('error'):
                            self.errors[key] = turn['error'].get('message', 'Turn failed')
                        self.persist()
                    else:
                        self.next_message(slot, ident)
            elif method == 'thread/tokenUsage/updated':
                view['_tokenUsage'] = p['tokenUsage']
                self.saved.setdefault('telemetry', {})[key] = p['tokenUsage']
                self.persist()
            elif method in ('thread/compacted', 'thread/contextCompacted'):
                view['_compacting'] = False
                view['_compactedAt'] = int(time.time())
            elif method.startswith('item/'):
                turn_id = p.get('turnId')
                turn = next((t for t in view.get('turns', []) if t['id'] == turn_id), None)
                if not turn:
                    turn = {'id': turn_id, 'items': [], 'status': 'inProgress'}
                    view.setdefault('turns', []).append(turn)
                items = turn.setdefault('items', [])
                item_id = p.get('itemId') or p.get('item', {}).get('id')
                item = next((v for v in items if v['id'] == item_id), None)
                if method in ('item/started', 'item/completed'):
                    if p['item'].get('type') == 'contextCompaction':
                        view['_compacting'] = method == 'item/started'
                        if method == 'item/completed':
                            view['_compactedAt'] = int(time.time())
                    if item:
                        item.update(p['item'])
                    else:
                        items.append(p['item'])
                elif item is not None and method == 'item/agentMessage/delta':
                    item['text'] = item.get('text', '') + p.get('delta', '')
                elif item is not None and method == 'item/reasoning/summaryTextDelta':
                    index = p.get('summaryIndex', 0)
                    summary = item.setdefault('summary', [])
                    while len(summary) <= index:
                        summary.append('')
                    summary[index] += p.get('delta', '')
                elif item is not None and method == 'item/commandExecution/outputDelta':
                    item['aggregatedOutput'] = item.get('aggregatedOutput', '') + p.get('delta', '')
            elif method == 'thread/name/updated':
                view['name'] = p.get('threadName')


    def message(self, slot, ident, data):
        text = str(data.get('text', '')).strip()
        images = data.get('images', [])
        if not text and not images:
            raise ValueError('Write a message or attach an image.')
        if data.get('approvalMode', 'ask') not in APPROVAL_MODES:
            raise ValueError('Choose a supported approval mode.')
        if len(text) > 200000 or len(images) > 10:
            raise ValueError('Message or attachment limit exceeded.')
        clean = []
        for path in images:
            candidate = Path(path).expanduser().resolve()
            if not candidate.is_file() or candidate.stat().st_size > 30 * 1024 * 1024:
                raise ValueError('Choose an image file under 30 MB.')
            with candidate.open('rb') as stream:
                header = stream.read(16)
            if not (header.startswith((b'\x89PNG', b'\xff\xd8\xff', b'GIF87a', b'GIF89a'))
                    or header[:4] == b'RIFF' and header[8:12] == b'WEBP'):
                raise ValueError('Choose a PNG, JPEG, GIF, or WebP image.')
            clean.append(str(candidate))
        return {'id': secrets.token_hex(8), 'text': text, 'images': clean,
                'model': data.get('model') or None, 'effort': data.get('effort') or None,
                'approvalMode': data.get('approvalMode', 'ask')}


    def launch(self, slot, ident, message):
        key = self.key(slot, ident)
        client = self.client(slot)
        if key not in self.views or not self.views[key].get('_resumed'):
            result = client.call('thread/resume', {'threadId': ident})
            self.views[key] = result['thread']
            self.views[key]['_resumed'] = True
        inputs = [{'type': 'text', 'text': message['text']}] if message['text'] else []
        inputs += [{'type': 'localImage', 'path': path} for path in message['images']]
        self.errors.pop(key, None)
        result = client.call('turn/start', {'threadId': ident, 'input': inputs,
                                          'model': message['model'], 'effort': message['effort'],
                                          **APPROVAL_MODES[message.get('approvalMode', 'ask')]})
        self.active[key] = result['turn']['id']
        self.views[key]['_model'] = message['model']
        self.views[key]['_effort'] = message['effort']
        self.views[key]['_approvalMode'] = message.get('approvalMode', 'ask')
        self.saved.setdefault('settings', {})[key] = {'model': message['model'], 'effort': message['effort'], 'approvalMode': message.get('approvalMode', 'ask')}
        self.persist()


    def next_message(self, slot, ident):
        key = self.key(slot, ident)
        pending = self.saved.setdefault('queues', {}).setdefault(key, [])
        if not pending or self.saved.get('paused', {}).get(key) or key in self.active:
            return
        # Keep the message durable until dispatch is confirmed. A crash during the
        # request leaves it paused on restart, requiring a conversation check.
        message = pending[0]
        try:
            self.launch(slot, ident, message)
            pending.pop(0)
            self.persist()
        except Exception as exc:
            self.saved.setdefault('paused', {})[key] = True
            self.errors[key] = 'Send could not be confirmed. Check the conversation before retrying: ' + str(exc)
            self.persist()


    def action(self, data):
        with self.lock:
            slot, action, ident = data.get('slot'), data['action'], data.get('threadId')
            if slot not in load(self.root)['accounts']:
                raise ValueError('Unknown account')
            key = self.key(slot, ident) if ident else None
            if action == 'new':
                path = Path(data['cwd']).expanduser().resolve()
                if not path.is_dir():
                    raise ValueError('Choose an existing project folder.')
                result = self.client(slot).call('thread/start', {'cwd': str(path), 'model': data.get('model'),
                    'approvalPolicy': 'on-request', 'sandbox': 'workspace-write'})
                view = result['thread']
                view['_resumed'] = True
                self.views[self.key(slot, view['id'])] = view
                self.revision += 1
                return {'threadId': view['id']}
            elif action == 'send':
                message = self.message(slot, ident, data)
                self.view(slot, ident)
                pending = self.saved.setdefault('queues', {}).setdefault(key, [])
                if not pending and key not in self.active:
                    self.saved.setdefault('paused', {})[key] = False
                pending.append(message)
                self.persist()
                self.next_message(slot, ident)
            elif action == 'steer':
                if key not in self.active:
                    raise ValueError('This chat is no longer running. Send normally.')
                message = self.message(slot, ident, data)
                if message['model'] != self.views[key].get('_model') or message['effort'] != self.views[key].get('_effort') or message['approvalMode'] != self.views[key].get('_approvalMode', 'ask'):
                    raise ValueError('Queue this message to change the model, reasoning, or approval mode next turn.')
                inputs = [{'type': 'text', 'text': message['text']}] if message['text'] else []
                inputs += [{'type': 'localImage', 'path': p} for p in message['images']]
                self.client(slot).call('turn/steer', {'threadId': ident, 'expectedTurnId': self.active[key], 'input': inputs})
            elif action == 'steerQueue':
                pending = self.saved.setdefault('queues', {}).setdefault(key, [])
                messages = [m for m in pending if not data.get('id') or m['id'] == data['id']]
                if not messages:
                    return
                view = self.view(slot, ident)
                first = messages[0]
                settings = ('model', 'effort', 'approvalMode')
                if any(any(m.get(field) != first.get(field) for field in settings) for m in messages):
                    raise ValueError('Queued messages use different settings. Steer them separately or let them run in order.')
                combined = {**first, 'text': '\n\n'.join(m['text'] for m in messages if m['text']),
                            'images': [image for m in messages for image in m['images']]}
                if key in self.active and any(first.get(field) != view.get('_' + field, 'ask' if field == 'approvalMode' else None) for field in settings):
                    raise ValueError('Model or approval changes need a new turn. Leave these messages queued until the current turn finishes.')
                try:
                    if key in self.active:
                        inputs = [{'type': 'text', 'text': combined['text']}] if combined['text'] else []
                        inputs += [{'type': 'localImage', 'path': path} for path in combined['images']]
                        self.client(slot).call('turn/steer', {'threadId': ident, 'expectedTurnId': self.active[key], 'input': inputs})
                    else:
                        self.launch(slot, ident, combined)
                except Exception as error:
                    self.saved.setdefault('paused', {})[key] = True
                    self.errors[key] = 'Dispatch could not be confirmed. Queue retained and paused; check the conversation before retrying: ' + str(error)
                    self.persist()
                    raise
                sent = {m['id'] for m in messages}
                pending[:] = [m for m in pending if m['id'] not in sent]
                self.errors.pop(key, None)
                self.persist()
            elif action == 'compact':
                if key in self.active:
                    raise ValueError('Stop the active turn before compacting this chat.')
                self.client(slot).call('thread/compact/start', {'threadId': ident})
                self.views[key]['_compacting'] = True
                self.revision += 1
            elif action == 'stop':
                self.saved.setdefault('paused', {})[key] = True
                self.persist()
                if key in self.active:
                    self.client(slot).call('turn/interrupt', {'threadId': ident, 'turnId': self.active[key]})
            elif action == 'queue':
                pending = self.saved.setdefault('queues', {}).setdefault(key, [])
                index = next(i for i, m in enumerate(pending) if m['id'] == data['id'])
                if data.get('delete'):
                    pending.pop(index)
                else:
                    text = str(data['text']).strip()
                    if not text and not pending[index]['images']:
                        raise ValueError('Queued message cannot be empty.')
                    pending[index]['text'] = text
                self.persist()
            elif action == 'resumeQueue':
                self.saved.setdefault('paused', {})[key] = False
                self.persist()
                self.next_message(slot, ident)
            elif action == 'rename':
                name = str(data['name']).strip()[:200]
                if not name:
                    raise ValueError('Chat title cannot be empty.')
                self.client(slot).call('thread/name/set', {'threadId': ident, 'name': name})
                if key in self.views:
                    self.views[key]['name'] = name
                self.revision += 1
            elif action in ('archive', 'unarchive'):
                if key in self.active or self.saved.get('queues', {}).get(key):
                    raise ValueError('Stop this chat and clear its queue before archiving.')
                self.client(slot).call('thread/' + action, {'threadId': ident})
                self.revision += 1
            elif action == 'answer':
                request_key = slot + ':' + str(data['requestId'])
                req = self.requests[request_key]
                method, p = req['method'], req['params']
                if method == 'item/tool/requestUserInput':
                    result = {'answers': {q['id']: {'answers': [str(data.get('answers', {}).get(q['id'], ''))]} for q in p['questions']}}
                elif method == 'item/permissions/requestApproval':
                    result = {'permissions': p.get('permissions', {}) if data.get('accept') else {}, 'scope': 'turn'}
                else:
                    result = {'decision': 'accept' if data.get('accept') else 'decline'}
                self.client(slot).write({'id': req['id'], 'result': result})
                del self.requests[request_key]
                self.revision += 1
            else:
                raise ValueError('Unknown action')
            return {'ok': True}
