#!/usr/bin/env python3
"""Local deterministic demo/test backend. No credentials or remote services."""
import json
import os
from pathlib import Path
import sqlite3
import sys
import threading
import time

if '--version' in sys.argv:
    print('codex-cli fixture')
    raise SystemExit(0)

home = Path(os.environ['CODEX_HOME'])
lock = threading.Lock()
thread = {'id': 'fixture-' + str(os.getpid()), 'cwd': os.getcwd(), 'name': '', 'turns': []}
active = None
counter = 0

def emit(value):
    with lock:
        print(json.dumps(value), flush=True)

def event(method, **params):
    emit({'method': method, 'params': {'threadId': thread['id'], **params}})

def persist():
    (home / ('fixture-' + thread['id'] + '.json')).write_text(json.dumps(thread))

def controls():
    path = home / 'control.json'
    while True:
        if path.exists():
            try:
                data = json.loads(path.read_text())
                path.unlink()
                if data['action'] == 'complete' and active:
                    thread['turns'][-1]['status'] = 'completed'
                    persist()
                    event('turn/completed', turn={'id': active, 'status': 'completed', 'items': []})
                elif data['action'] == 'append' and active:
                    item = thread['turns'][-1]['items'][-1]
                    item['text'] += data['text']
                    persist()
                    event('item/agentMessage/delta', turnId=active, itemId=item['id'], delta=data['text'])
                elif data['action'] == 'approval':
                    emit({'id': 123, 'method': 'item/commandExecution/requestApproval',
                          'params': {'threadId': thread['id'], 'turnId': active, 'command': 'echo fixture', 'reason': 'Fixture approval'}})
            except (OSError, ValueError):
                pass
        time.sleep(.05)

threading.Thread(target=controls, daemon=True).start()
for line in sys.stdin:
    request = json.loads(line)
    with (home / 'rpc.jsonl').open('a') as out:
        out.write(json.dumps(request) + '\n')
    method, p = request.get('method'), request.get('params', {})
    if not method or 'id' not in request:
        continue
    result = {}
    if method == 'account/rateLimits/read':
        result = {'rateLimits': {'primary': {'usedPercent': 23, 'windowDurationMins': 300, 'resetsAt': int(time.time()) + 3600}, 'secondary': {'usedPercent': 38, 'windowDurationMins': 10080, 'resetsAt': int(time.time()) + 86400}}}
    elif method == 'model/list':
        model_pairs = [('demo-model', 'Demo model'), ('demo-lite', 'Demo lite')] if (home / 'demo-mode').exists() else [('fixture-sol', 'Fixture Sol'), ('fixture-luna', 'Fixture Luna')]
        result = {'data': [{'model': name, 'displayName': label, 'isDefault': n == 0,
                           'defaultReasoningEffort': 'high',
                           'supportedReasoningEfforts': [{'reasoningEffort': 'medium'}, {'reasoningEffort': 'high'}]}
                          for n, (name, label) in enumerate(model_pairs)]}
    elif method == 'thread/start':
        thread['cwd'] = p.get('cwd', thread['cwd'])
        result = {'thread': thread}
    elif method in ('thread/read', 'thread/resume'):
        path = home / ('fixture-' + p['threadId'] + '.json')
        if path.exists():
            thread = json.loads(path.read_text())
            counter = len(thread['turns'])
        elif p['threadId'] != thread['id']:
            emit({'id': request['id'], 'error': {'code': -32000, 'message': 'thread not loaded: ' + p['threadId']}})
            continue
        result = {'thread': thread}
    elif method in ('thread/archive', 'thread/unarchive', 'thread/delete'):
        if (home / 'fail-lifecycle').exists():
            emit({'id': request['id'], 'error': {'code': -32000, 'message': 'Fixture lifecycle failure'}})
            continue
        with sqlite3.connect(home / 'state_5.sqlite') as db:
            if method == 'thread/delete':
                db.execute('DELETE FROM threads WHERE id = ?', (p['threadId'],))
                (home / ('fixture-' + p['threadId'] + '.json')).unlink(missing_ok=True)
            else:
                db.execute('UPDATE threads SET archived = ? WHERE id = ?', (int(method == 'thread/archive'), p['threadId']))
    elif method == 'turn/start':
        counter += 1
        active = 'turn-' + str(counter)
        turn = {'id': active, 'status': 'inProgress', 'items': []}
        thread['turns'].append(turn)
        result = {'turn': dict(turn)}
        text = next((v['text'] for v in p['input'] if v['type'] == 'text'), 'Image')
        with sqlite3.connect(home / 'state_5.sqlite') as db:
            db.execute('DELETE FROM threads WHERE id = ?', (thread['id'],))
            db.execute('INSERT INTO threads VALUES(?,?,?,0,1,?)', (thread['id'], text[:50], thread['cwd'], int(time.time())))
    emit({'id': request['id'], 'result': result})
    if method == 'turn/start':
        event('turn/started', turn=turn)
        response = (home / 'reply.md').read_text() if (home / 'reply.md').is_file() else os.environ.get('CODEX_HUB_DEMO_REPLY', 'Fixture response. [Open docs](https://example.com/docs)')
        items = [{'id': active + '-user', 'type': 'userMessage', 'content': p['input']},
                 {'id': active + '-thinking', 'type': 'reasoning', 'summary': ['Checking the project structure and existing tests.']},
                 {'id': active + '-tool', 'type': 'commandExecution', 'command': 'python -m pytest', 'aggregatedOutput': '3 tests passed'},
                 {'id': active + '-reply', 'type': 'agentMessage', 'text': ''}]
        for item in items:
            event('item/started', turnId=active, item=item)
            if item['type'] in ('reasoning', 'commandExecution'):
                event('item/completed', turnId=active, item=item)
        event('item/agentMessage/delta', turnId=active, itemId=active + '-reply', delta=response)
        items[-1]['text'] = response
        turn['items'] = items
        persist()
        event('thread/tokenUsage/updated', turnId=active, tokenUsage={'last': {'totalTokens': 15000, 'inputTokens': 14000, 'outputTokens': 1000, 'cachedInputTokens': 0, 'reasoningOutputTokens': 0}, 'total': {'totalTokens': 90000}, 'modelContextWindow': 128000})
    elif method == 'turn/interrupt':
        thread['turns'][-1]['status'] = 'interrupted'
        persist()
        event('turn/completed', turn={'id': active, 'status': 'interrupted', 'items': []})
    elif method == 'thread/compact/start':
        event('item/started', turnId=active or 'compact', item={'id': 'compact', 'type': 'contextCompaction'})
        event('item/completed', turnId=active or 'compact', item={'id': 'compact', 'type': 'contextCompaction'})
