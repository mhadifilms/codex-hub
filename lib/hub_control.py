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


def submit(root, slot, thread, text, objective=None, require_active=False):
    ident = str(uuid.uuid4())
    command = {'id': ident, 'text': text, 'objective': objective,
               'requireActive': require_active, 'createdAt': time.time()}
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
    if time.time() - command['createdAt'] > 120 or blocked(chat.snapshot, chat.fields.get('prompt', ''), chat.images):
        finish(claimed, 'skipped', 'Chat is busy, has user work, or command expired.')
        return
    chat.control_claim = claimed
    chat.pending_action = 'control'
    chat.pending = chat.executor.submit(execute, chat.runtime, chat.slot, chat.ident,
                                       command, chat.model, chat.effort)


def execute(runtime, slot, thread, command, model, effort):
    # Recheck under the same runtime lock used by incoming turn notifications.
    with runtime.lock:
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


def finish(claimed, status, reason=''):
    write(claimed.with_suffix('.result'), {'status': status, 'reason': reason, 'at': time.time()})
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


def supervise(root, config, path, windows, reload_chat):
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
            result = {'at': time.time(), 'tasks': check(root, config, plan['tasks'], windows, reload_chat, last)}
            write(Path(root) / 'supervisor-status.json', result)
            with (Path(root) / 'supervisor-events.jsonl').open('a') as log:
                log.write(json.dumps(result) + '\n')
            print(json.dumps(result), flush=True)
            time.sleep(min(interval, max(0, deadline - time.monotonic())))
