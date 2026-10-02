"""Terminal runtime lifecycle checks; fake RPC only, no account access."""
import base64
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
import threading
import unittest

spec = importlib.util.spec_from_file_location('hub_runtime', Path(__file__).resolve().parents[1] / 'lib/hub_runtime.py')
runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)
PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jN1sAAAAASUVORK5CYII=')


class FakeRpc:
    def __init__(self, slot, callback):
        self.slot, self.callback = slot, callback
        self.calls, self.responses, self.threads = [], [], {}
        self.fail = False

    def call(self, method, params=None):
        params = params or {}
        self.calls.append((method, copy.deepcopy(params)))
        if self.fail:
            raise RuntimeError('Simulated connection failure')
        if method == 'model/list':
            return {'data': [{'model': 'fixture-model', 'displayName': 'Fixture model', 'isDefault': True,
                             'defaultReasoningEffort': 'high', 'supportedReasoningEfforts': [{'reasoningEffort': 'high'}]}]}
        if method == 'thread/list':
            return {'data': list(self.threads.values()), 'nextCursor': None}
        if method == 'thread/start':
            ident = self.slot + '-thread-' + str(len(self.threads))
            t = {'id': ident, 'cwd': params['cwd'], 'name': 'Fixture chat', 'turns': [], 'updatedAt': 1}
            self.threads[ident] = t
            return {'thread': copy.deepcopy(t)}
        if method in ('thread/read', 'thread/resume'):
            return {'thread': copy.deepcopy(self.threads[params['threadId']])}
        if method == 'turn/start':
            return {'turn': {'id': 'turn-' + str(len(self.calls)), 'status': 'inProgress', 'items': []}}
        if method == 'thread/name/set':
            self.threads[params['threadId']]['name'] = params['name']
        return {}

    def write(self, result):
        self.responses.append(result)


class HubTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / 'config.json').write_text(json.dumps({'schemaVersion': 1, 'defaultAccount': '1', 'accounts': {slot: {'label': 'Account ' + slot, 'home': str(self.root / slot)} for slot in ('1', '2', '3')}}))
        self.hub = runtime.Hub(self.root, FakeRpc)
        self.ident = self.hub.action({'action': 'new', 'slot': '1', 'cwd': str(self.root)})['threadId']

    def tearDown(self):
        self.temp.cleanup()

    def act(self, action, **data):
        return self.hub.action({'action': action, 'slot': '1', 'threadId': self.ident, **data})

    def send(self, text):
        return self.act('send', text=text, model='fixture-model', effort='high')

    def complete(self, status='completed'):
        active = self.hub.active[self.hub.key('1', self.ident)]
        self.hub.event('1', {'method': 'turn/completed', 'params': {'threadId': self.ident,
                        'turn': {'id': active, 'status': status, 'items': []}}})

    def test_queue_edit_remove_and_dispatch(self):
        self.send('first;$HOME\nsecond line')
        self.send('queued')
        self.send('remove me')
        detail = self.hub.thread('1', self.ident)
        self.assertEqual(len(detail['queue']), 2)
        self.act('queue', id=detail['queue'][0]['id'], text='edited')
        self.act('queue', id=detail['queue'][1]['id'], delete=True)
        calls = self.hub.clients['1'].calls
        self.assertEqual([p['input'][0]['text'] for m, p in calls if m == 'turn/start'], ['first;$HOME\nsecond line'])
        self.complete()
        self.assertEqual([p['input'][0]['text'] for m, p in calls if m == 'turn/start'], ['first;$HOME\nsecond line', 'edited'])
        self.assertEqual(self.hub.thread('1', self.ident)['queue'], [])

    def test_stop_failed_turn_and_restart_pause_queue(self):
        self.send('first'); self.send('later')
        self.act('stop'); self.complete('interrupted')
        self.assertEqual(len(self.hub.thread('1', self.ident)['queue']), 1)
        restored = runtime.Hub(self.root, FakeRpc)
        self.assertTrue(restored.saved['paused']['1:' + self.ident])
        self.act('resumeQueue')
        self.assertEqual(self.hub.thread('1', self.ident)['queue'], [])
        self.send('after failure'); self.complete('failed')
        self.assertTrue(self.hub.thread('1', self.ident)['paused'])

    def test_uncertain_send_keeps_queue_and_pauses(self):
        self.hub.clients['1'].fail = True
        self.send('recover me')
        state = self.hub.thread('1', self.ident)
        self.assertTrue(state['paused'])
        self.assertEqual(state['queue'][0]['text'], 'recover me')
        self.assertIn('could not be confirmed', state['error'])

    def test_steering_and_model_selection(self):
        self.send('first')
        self.act('steer', text='change direction', model='fixture-model', effort='high')
        method, params = self.hub.clients['1'].calls[-1]
        self.assertEqual(method, 'turn/steer')
        self.assertEqual(params['expectedTurnId'], self.hub.thread('1', self.ident)['active'])
        with self.assertRaises(ValueError):
            self.act('steer', text='new model', model='different', effort='high')

    def test_queued_steering_removes_only_confirmed_messages(self):
        self.send('first')
        self.send('queued one')
        self.send('queued two')
        queued = self.hub.thread('1', self.ident)['queue']
        self.act('steerQueue', id=queued[1]['id'])
        self.assertEqual(self.hub.clients['1'].calls[-1][0], 'turn/steer')
        self.assertEqual(self.hub.clients['1'].calls[-1][1]['input'][0]['text'], 'queued two')
        self.assertEqual([m['text'] for m in self.hub.thread('1', self.ident)['queue']], ['queued one'])
        self.send('queued three')
        self.act('steerQueue')
        self.assertEqual(self.hub.clients['1'].calls[-1][1]['input'][0]['text'], 'queued one\n\nqueued three')
        self.assertEqual(self.hub.thread('1', self.ident)['queue'], [])

    def test_uncertain_queued_steering_does_not_replay(self):
        self.send('first')
        self.send('keep me')
        self.hub.clients['1'].fail = True
        with self.assertRaises(RuntimeError):
            self.act('steerQueue')
        self.hub.clients['1'].fail = False
        self.complete()
        self.assertTrue(self.hub.thread('1', self.ident)['paused'])
        self.assertEqual([m['text'] for m in self.hub.thread('1', self.ident)['queue']], ['keep me'])
        self.assertEqual(len([m for m, _ in self.hub.clients['1'].calls if m == 'turn/start']), 1)

    def test_account_isolation(self):
        second = self.hub.action({'action': 'new', 'slot': '2', 'cwd': str(self.root)})['threadId']
        self.send('account one')
        self.hub.action({'action': 'send', 'slot': '2', 'threadId': second, 'text': 'account two'})
        self.assertEqual(self.hub.clients['1'].calls[-1][1]['input'][0]['text'], 'account one')
        self.assertEqual(self.hub.clients['2'].calls[-1][1]['input'][0]['text'], 'account two')

    def test_approval_must_be_explicit_and_slot_scoped(self):
        p = {'threadId': self.ident, 'turnId': 't', 'command': 'echo test'}
        self.hub.event('1', {'method': 'item/commandExecution/requestApproval', 'id': 4, 'params': p})
        self.assertEqual(self.hub.clients['1'].responses, [])
        with self.assertRaises(KeyError):
            self.hub.action({'action': 'answer', 'slot': '2', 'requestId': 4, 'accept': True})
        self.act('answer', requestId=4, accept=False)
        self.assertEqual(self.hub.clients['1'].responses[-1], {'id': 4, 'result': {'decision': 'decline'}})

    def test_streaming_and_completion_preserve_items(self):
        self.send('hello')
        active = self.hub.thread('1', self.ident)['active']
        self.hub.event('1', {'method': 'item/started', 'params': {'threadId': self.ident, 'turnId': active,
                         'item': {'id': 'msg', 'type': 'agentMessage', 'text': ''}}})
        self.hub.event('1', {'method': 'item/agentMessage/delta', 'params': {'threadId': self.ident,
                         'turnId': active, 'itemId': 'msg', 'delta': 'Hello'}})
        self.complete()
        self.assertEqual(self.hub.thread('1', self.ident)['thread']['turns'][-1]['items'][0]['text'], 'Hello')

    def test_approval_mode_and_compaction(self):
        self.act('send', text='explicit selection', approvalMode='auto')
        params = self.hub.clients['1'].calls[-1][1]
        self.assertEqual(params['approvalPolicy'], 'on-request')
        self.assertEqual(params['approvalsReviewer'], 'auto_review')
        self.assertEqual(params['sandboxPolicy']['type'], 'workspaceWrite')
        with self.assertRaises(ValueError):
            self.act('compact')
        self.complete()
        self.act('compact')
        self.assertEqual(self.hub.clients['1'].calls[-1][0], 'thread/compact/start')
        self.hub.event('1', {'method': 'thread/tokenUsage/updated', 'params': {'threadId': self.ident, 'turnId': 't', 'tokenUsage': {'last': {'totalTokens': 14000}, 'total': {'totalTokens': 90000}, 'modelContextWindow': 100000}}})
        self.assertEqual(self.hub.thread('1', self.ident)['thread']['_tokenUsage']['last']['totalTokens'], 14000)
        self.act('send', text='explicit full access', approvalMode='full')
        params = self.hub.clients['1'].calls[-1][1]
        self.assertEqual(params['approvalPolicy'], 'never')
        self.assertEqual(params['sandboxPolicy']['type'], 'dangerFullAccess')

    def test_image_validation_and_local_input(self):
        image = self.root / 'sample.png'
        image.write_bytes(PNG)
        self.act('send', text='Image', images=[str(image)])
        self.assertEqual(self.hub.clients['1'].calls[-1][1]['input'][-1], {'type': 'localImage', 'path': str(image.resolve())})
        text = self.root / 'not-image.png'
        text.write_text('Not an image')
        with self.assertRaises(ValueError):
            self.act('send', images=[str(text)])

    def test_per_chat_persistence(self):
        first = self.root / '1' / 'first.json'
        second = self.root / '1' / 'second.json'
        a = runtime.Hub(self.root, FakeRpc, first)
        b = runtime.Hub(self.root, FakeRpc, second)
        a.saved['draft'] = {'text': 'first draft'}
        b.saved['draft'] = {'text': 'second draft'}
        a.persist(); b.persist()
        self.assertEqual(runtime.Hub(self.root, FakeRpc, first).saved['draft']['text'], 'first draft')
        self.assertEqual(runtime.Hub(self.root, FakeRpc, second).saved['draft']['text'], 'second draft')

    def test_unknown_client_request_is_explicitly_rejected(self):
        self.hub.event('1', {'id': 9, 'method': 'unknown/tool', 'params': {'threadId': self.ident}})
        self.assertEqual(self.hub.clients['1'].responses[-1]['error']['code'], -32601)
        self.assertIn('unsupported interaction', self.hub.thread('1', self.ident)['error'])


class InstallationTests(unittest.TestCase):
    def test_runtime_discovery_with_existing_local_lib(self):
        import os
        import shutil
        import subprocess
        import sys
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            local = home / '.local'
            (local / 'bin').mkdir(parents=True)
            (local / 'lib').mkdir()
            shared = local / 'share/codex-hub'
            shared.mkdir(parents=True)
            repo = Path(__file__).resolve().parents[1]
            shutil.copyfile(repo / 'bin/codex-hub-tui', local / 'bin/codex-hub-tui')
            for library in (repo / 'lib').glob('*.py'):
                shutil.copyfile(library, shared / library.name)
            shutil.copyfile(repo / 'VERSION', shared / 'VERSION')
            subprocess.run([sys.executable, '-c',
                            "import runpy,sys; runpy.run_path(sys.argv[1], run_name='installed_hub'); import hub_runtime",
                            str(local / 'bin/codex-hub-tui')],
                           env={**os.environ, 'HOME': str(home)}, check=True, capture_output=True)


if __name__ == '__main__':
    unittest.main()
