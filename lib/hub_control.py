"""Private, durable commands to a chat's owning frontend; no second model client."""
import json
from pathlib import Path
import re
import sqlite3
import time
import uuid


def directory(root, slot, thread):
    if not re.fullmatch(r'[A-Za-z0-9_-]+', slot) or not re.fullmatch(r'[A-Za-z0-9_-]+', thread):
        raise ValueError('Invalid account or thread ID.')
    return Path(root) / 'control' / slot / thread


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value))
    temporary.chmod(0o600)
    temporary.replace(path)


def submit(root, slot, thread, text, objective=None, require_active=False, action='send'):
    ident = str(uuid.uuid4())
    command = {'id': ident, 'text': text, 'objective': objective,
               'requireActive': require_active, 'createdAt': time.time(), 'action': action}
    write(directory(root, slot, thread) / (ident + '.pending'), command)
    return ident


def blocked(snapshot, draft, images):
    return bool(snapshot.get('active') or snapshot.get('requests') or snapshot.get('queue')
                or snapshot.get('paused') or snapshot.get('error') or draft.strip() or images)


def poll(chat, root):
    if not chat.ready or chat.pending:
        return
    folder = directory(root, chat.slot, chat.ident)
    pending = sorted(folder.glob('*.pending'))
    if not pending:
        return
    path = pending[0]
    claimed = path.with_suffix('.claimed')
    path.rename(claimed)
    command = json.loads(claimed.read_text())
    special = command.get('action') in ('prepareTransfer', 'recover', 'resumeMaintenance')
    unavailable = (bool(chat.snapshot.get('active') or chat.snapshot.get('requests')
                        or (command.get('action') != 'prepareTransfer' and
                            (chat.fields.get('prompt', '').strip() or chat.images or chat.snapshot.get('queue'))))
                   if special else
                   blocked(chat.snapshot, chat.fields.get('prompt', ''), chat.images))
    if time.time() - command['createdAt'] > 120 or unavailable:
        finish(claimed, 'skipped', 'Chat is busy, has user work, or command expired.')
        return
    chat.control_claim = claimed
    chat.control_text = command['text']
    chat.pending_action = 'control'
    chat.pending = chat.executor.submit(execute, chat.runtime, chat.slot, chat.ident,
                                       command, chat.model, chat.effort)


def execute(runtime, slot, thread, command, model, effort):
    # Recheck under the same runtime lock used by incoming turn notifications.
    with runtime.lock:
        if command.get('action') in ('recover', 'resumeMaintenance'):
            snapshot = runtime.thread(slot, thread)
            if snapshot.get('active') or snapshot.get('requests') or snapshot.get('queue'):
                return {'status': 'skipped', 'reason': 'Chat has pending work.'}
            goal = runtime.client(slot).call('thread/goal/get', {'threadId': thread}).get('goal')
            if command['action'] == 'recover' and (not goal or goal['status'] not in ('active', 'blocked', 'usageLimited')):
                return {'status': 'skipped', 'reason': 'Goal is paused, complete, or budget-limited.'}
            key = runtime.key(slot, thread)
            runtime.saved.setdefault('paused', {})[key] = False
            runtime.errors.pop(key, None)
            runtime.persist()
        if command.get('action') == 'prepareTransfer':
            snapshot = runtime.thread(slot, thread)
            if snapshot.get('active') or snapshot.get('requests'):
                return {'status': 'skipped', 'reason': 'Chat became busy.'}
            goal = runtime.client(slot).call('thread/goal/get', {'threadId': thread}).get('goal')
            if goal and goal.get('tokenBudget') is not None:
                raise ValueError('Budgeted goals require manual handoff.')
            if goal and goal['status'] != 'complete':
                runtime.client(slot).call('thread/goal/set', {'threadId': thread, 'status': 'paused'})
            return {'status': 'prepared', 'goal': goal}
        if blocked(runtime.thread(slot, thread), '', []):
            return {'status': 'skipped', 'reason': 'Chat became busy.'}
        if command['requireActive']:
            goal = runtime.client(slot).call('thread/goal/get', {'threadId': thread}).get('goal')
            if not goal or goal['status'] != 'active':
                return {'status': 'skipped', 'reason': 'Goal is not active.'}
        runtime.action({'action': 'send', 'slot': slot, 'threadId': thread,
                        'text': command['text'], 'model': model, 'effort': effort,
                        'approvalMode': 'auto'})
        if command.get('objective'):
            runtime.client(slot).call('thread/goal/set', {'threadId': thread,
                                     'objective': command['objective'], 'status': 'active'})
        return {'status': 'sent'}


def finish(claimed, status, reason='', **data):
    write(claimed.with_suffix('.result'), {'status': status, 'reason': reason, 'at': time.time(), **data})
    claimed.unlink(missing_ok=True)


def goal(home, thread):
    databases = sorted(Path(home).glob('goals_*.sqlite'), key=lambda p: int(p.stem.split('_')[-1]))
    if not databases:
        return None
    with sqlite3.connect(databases[-1].as_uri() + '?mode=ro', uri=True) as db:
        db.row_factory = sqlite3.Row
        row = db.execute('SELECT status, objective FROM thread_goals WHERE thread_id=?', (thread,)).fetchone()
        return dict(row) if row else None


def check(root, config, tasks, windows, reload_chat, last):
    observations = []
    for task in tasks:
        slot, thread = task['account'], task['thread']
        key = slot + ':' + thread
        try:
            current = goal(config['accounts'][slot]['home'], thread)
            window = next((w for w in windows() if w['slot'] == slot and w['thread'] == thread), None)
            status = current['status'] if current else 'no goal'
            saved_path = Path(root) / 'tui-state' / slot / (thread + '.json')
            saved = json.loads(saved_path.read_text()) if saved_path.exists() else {}
            user_work = bool(saved.get('draft', {}).get('text', '').strip()
                             or saved.get('draft', {}).get('images') or saved.get('queues', {}).get(key)
                             or saved.get('paused', {}).get(key))
            folder = directory(root, slot, thread)
            outstanding = list(folder.glob('*.pending')) + list(folder.glob('*.claimed'))
            uncertain = any(json.loads(p.read_text()).get('status') == 'uncertain' for p in folder.glob('*.result'))
            # Never retry an uncertain dispatch, overwrite a draft, or revive a paused/limited goal.
            previous = last.get(key, {})
            last[key] = {'busy': window['busy'] if window else None, 'at': time.time()}
            if uncertain:
                status = 'uncertain dispatch; manual check required'
            if status == 'active' and window and window['busy'] == '0' and not user_work and not outstanding:
                if previous.get('busy') == '0' and time.time() - previous['at'] >= 120:
                    if window.get('control') != '1':
                        reload_chat(window)
                        status = 'reconnected; check next hour'
                    else:
                        submit(root, slot, thread, task['prompt'], require_active=True)
                        status = 'continuation requested'
            observations.append({'account': slot, 'thread': thread, 'goal': status,
                                 'busy': window['busy'] if window else None})
        except Exception as error:
            observations.append({'account': slot, 'thread': thread, 'error': str(error)})
    return observations


def capacity(snapshot):
    if snapshot.get('error'):
        return None
    values = [snapshot.get(k) for k in ('remainingPercent', 'sessionRemainingPercent')]
    values = [x for x in values if isinstance(x, (int, float))]
    return min(values) if values else None


def failover(root, plan, config, snapshots, windows, transfer):
    events = []
    for task in [*plan['tasks'], *([plan['coordinator']] if plan.get('coordinator') else [])]:
        slot, thread = task['account'], task['thread']
        if capacity(snapshots.get(slot, {})) != 0:
            continue
        window = next((w for w in windows() if w['slot'] == slot and w['thread'] == thread), None)
        if not window or window['busy'] != '0':
            continue
        current = goal(config['accounts'][slot]['home'], thread)
        if task is not plan.get('coordinator') and (not current or current['status'] not in ('active', 'usageLimited')):
            continue
        saved_path = Path(root) / 'tui-state' / slot / (thread + '.json')
        saved = json.loads(saved_path.read_text()) if saved_path.exists() else {}
        draft = saved.get('draft', {})
        if draft.get('text', '').strip() or draft.get('images') or saved.get('queues', {}).get(slot + ':' + thread):
            continue
        if saved.get('paused', {}).get(slot + ':' + thread) and current and current['status'] != 'usageLimited':
            continue
        folder = directory(root, slot, thread)
        if list(folder.glob('*.pending')) or list(folder.glob('*.claimed')):
            continue
        if any(json.loads(p.read_text()).get('status') == 'uncertain' for p in folder.glob('*.result')):
            continue
        choices = [(capacity(snapshots.get(other, {})), other) for other in config['accounts'] if other != slot]
        choices = [(remaining, other) for remaining, other in choices if remaining is not None and remaining > 0]
        if not choices:
            events.append({'thread': thread, 'error': 'No verified account capacity available.'})
            continue
        target = max(choices)[1]
        try:
            moved = transfer(slot, target, thread)
            task['account'] = target
            objective = moved.get('goal', {}).get('objective') if moved.get('goal') else None
            text = ('Account quota was exhausted; this is the authorized handoff continuation. '
                    'Reconcile existing remote jobs and logs before submitting any new work. '
                    'Preserve the existing objective, constraints, evidence, and human pauses.\n\n' + task['prompt'])
            submit(root, target, thread, text, objective, action='resumeMaintenance')
            events.append({'thread': thread, 'from': slot, 'to': target})
        except Exception as error:
            events.append({'thread': thread, 'error': str(error)})
    return events


def supervise(root, config, path, windows, reload_chat, usage=None, transfer=None):
    import fcntl
    plan = json.loads(Path(path).read_text())
    interval = float(plan.get('intervalSeconds', 3600))
    hours = float(plan.get('hours', 12))
    if interval < 120 or hours <= 0:
        raise ValueError('Use an interval of at least 120 seconds and positive hours.')
    lock_path = Path(root) / 'supervisor.lock'
    with lock_path.open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        deadline = time.monotonic() + hours * 3600
        last = {}
        while time.monotonic() < deadline:
            plan = json.loads(Path(path).read_text())
            config = __import__('hub_config').load(root)
            snapshots = {}
            if usage and plan.get('failover'):
                for slot in config['accounts']:
                    try:
                        snapshots[slot] = usage(slot)
                    except Exception as error:
                        snapshots[slot] = {'error': str(error)}
            moves = failover(root, plan, config, snapshots, windows, transfer) if snapshots and transfer else []
            if moves:
                write(Path(path), plan)
            result = {'at': time.time(), 'tasks': check(root, config, plan['tasks'], windows, reload_chat, last)}
            result.update(usage=snapshots, handoffs=moves)
            coordinator = plan.get('coordinator')
            if coordinator:
                window = next((w for w in windows() if w['slot'] == coordinator['account'] and w['thread'] == coordinator['thread']), None)
                if window and window['busy'] == '0':
                    folder = directory(root, coordinator['account'], coordinator['thread'])
                    if not list(folder.glob('*.pending')) and not list(folder.glob('*.claimed')):
                        submit(root, coordinator['account'], coordinator['thread'], coordinator['prompt'])
            write(Path(root) / 'supervisor-status.json', result)
            with (Path(root) / 'supervisor-events.jsonl').open('a') as log:
                log.write(json.dumps(result) + '\n')
            print(json.dumps(result), flush=True)
            time.sleep(min(interval, max(0, deadline - time.monotonic())))
