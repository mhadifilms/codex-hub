"""Move an idle chat after its owning process releases the rollout."""
import json
from pathlib import Path
import shutil
import sqlite3
import time
from hub_runtime import Rpc
import hub_control


def rollout(home, thread):
    databases = sorted(Path(home).glob('state_*.sqlite'), key=lambda p: int(p.stem.split('_')[-1]))
    if not databases:
        raise ValueError('No saved chat database.')
    with sqlite3.connect(databases[-1].as_uri() + '?mode=ro', uri=True) as db:
        row = db.execute('SELECT rollout_path FROM threads WHERE id=?', (thread,)).fetchone()
    if not row:
        raise ValueError('Chat has no saved history yet.')
    path = Path(row[0]).resolve()
    path.relative_to((Path(home) / 'sessions').resolve())
    with path.open() as source:
        meta = json.loads(source.readline())
    if meta.get('payload', {}).get('history_base'):
        raise ValueError('This chat has linked history segments; flatten them before handoff.')
    return path


def move(hub, source, target, thread):
    config = hub.hub_config.load(hub.ROOT)
    if source == target or source not in config['accounts'] or target not in config['accounts']:
        raise ValueError('Choose two different configured accounts.')
    window = next((w for w in hub.windows() if w['slot'] == source and w['thread'] == thread), None)
    if not window or window['busy'] != '0':
        raise ValueError('Move only a connected idle chat; stop an active turn first.')
    if any(w['slot'] == target and w['thread'] == thread for w in hub.windows()):
        raise ValueError('A copy of this chat is already open in the target account.')
    path = rollout(hub.account_home(source), thread)
    if hub.tmux('show-option', '-wv', '-t', window['id'], '@hub_control', check=False) != '1':
        hub.reload_chat(window)
        raise ValueError('Frontend updated. Retry after it connects.')
    ident = hub_control.submit(hub.ROOT, source, thread, '', action='prepareTransfer')
    result_path = hub_control.directory(hub.ROOT, source, thread) / (ident + '.result')
    deadline = time.monotonic() + 25
    while not result_path.exists():
        if time.monotonic() >= deadline:
            raise ValueError('Handoff acknowledgment unavailable; inspect before retrying.')
        time.sleep(.1)
    result = json.loads(result_path.read_text())
    if result['status'] != 'prepared':
        raise ValueError(result.get('reason') or 'Chat could not release its writer.')
    while hub.tmux('display-message', '-p', '-t', window['pane'], '#{pane_dead}') != '1':
        if time.monotonic() >= deadline:
            raise ValueError('Old writer has not exited; handoff stopped.')
        time.sleep(.1)
    destination = hub.account_home(target) / 'sessions' / path.relative_to(hub.account_home(source) / 'sessions')
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if destination.exists():
        backup = hub.ROOT / 'transfer-backups' / str(time.time_ns()) / destination.name
        backup.parent.mkdir(parents=True, mode=0o700)
        shutil.copy2(destination, backup)
    temporary = destination.with_suffix('.transfer')
    shutil.copyfile(path, temporary)
    temporary.chmod(0o600)
    temporary.replace(destination)
    client = Rpc(target, lambda *_: None, root=hub.ROOT)
    try:
        resumed = client.call('thread/resume', {'threadId': thread, 'cwd': window['path'],
                                              'approvalPolicy': 'on-request', 'approvalsReviewer': 'auto_review'})
        if resumed['thread']['id'] != thread:
            raise ValueError('Imported chat identity differs; handoff stopped.')
    finally:
        client.close()
    old_state = hub.ROOT / 'tui-state' / source / (thread + '.json')
    new_state = hub.ROOT / 'tui-state' / target / (thread + '.json')
    if old_state.exists():
        saved = json.loads(old_state.read_text())
        for group in ('queues', 'paused', 'settings', 'telemetry'):
            values = saved.get(group, {})
            if source + ':' + thread in values:
                values[target + ':' + thread] = values.pop(source + ':' + thread)
        hub_control.write(new_state, saved)
    def update(data):
        record = dict(data.setdefault('chats', {}).setdefault(source, {}).get(thread, {}))
        data['chats'][source].setdefault(thread, {}).update(open=False, movedTo=target)
        record.pop('movedTo', None)
        record.update(open=True, has_content=True, importedHistory=True)
        data['chats'].setdefault(target, {})[thread] = record
        name = data.setdefault('names', {}).setdefault(source, {}).get(thread, window['name'])
        data['names'].setdefault(target, {})[thread] = name
        pins = data.setdefault('pins', {}).setdefault(source, [])
        if thread in pins:
            pins.remove(thread)
            target_pins = data['pins'].setdefault(target, [])
            if thread not in target_pins:
                target_pins.append(thread)
    hub.update_state(update)
    hub.tmux('kill-window', '-t', window['id'])
    hub.new_chat(target, window['path'], title=window['name'], thread=thread, background=True)
    goal = result.get('goal')
    if goal and goal['status'] not in ('complete', 'paused', 'budgetLimited'):
        # Only the hourly coordinator decides whether to continue a transferred goal.
        client = Rpc(target, lambda *_: None, root=hub.ROOT)
        try:
            client.call('thread/goal/set', {'threadId': thread, 'objective': goal['objective'], 'status': 'paused'})
        finally:
            client.close()
    return {'account': target, 'thread': thread, 'goal': goal}
