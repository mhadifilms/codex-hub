"""Integration checks with a disposable tmux server, fake Codex, and real mouse input."""
import importlib.machinery
import importlib.util
import fcntl
from contextlib import closing
import json
import os
from pathlib import Path
import pty
import re
import select
import shutil
import sqlite3
import struct
import subprocess
import tempfile
import termios
import time
import unittest

REPO = Path(__file__).resolve().parents[1]
loader = importlib.machinery.SourceFileLoader('hub', str(REPO / 'bin/codex-hub-tui'))
spec = importlib.util.spec_from_loader(loader.name, loader)
hub = importlib.util.module_from_spec(spec)
loader.exec_module(hub)


class HubIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scratch = tempfile.TemporaryDirectory(prefix='codex-hub-test-')
        cls.root = Path(cls.scratch.name).resolve()
        hub.ROOT, hub.SOCKET = cls.root, cls.root / 'tmux.sock'
        shutil.copy(REPO / 'tmux.conf', cls.root / 'tmux.conf')
        cls.project = cls.root / 'project with spaces'
        cls.project.mkdir()
        cls.fakebin = cls.root / 'bin'
        cls.fakebin.mkdir()
        fake = cls.fakebin / 'codex'
        fake.write_text('#!/usr/bin/env python3\nimport os,json,time\nfrom pathlib import Path\n'
                        'p=Path(os.environ["CODEX_HOME"])/"invoked.json"\n'
                        'p.write_text(json.dumps({"home":str(p.parent),"cwd":os.getcwd(),'
                        '"args":__import__("sys").argv[1:],"api":os.environ.get("OPENAI_API_KEY")}))\n'
                        'print("FAKE CODEX — terminal remains running",flush=True)\ntime.sleep(600)\n')
        fake.chmod(0o700)
        cls.oldenv = os.environ.copy()
        os.environ['CODEX_HUB_ROOT'] = str(cls.root)
        os.environ['CODEX_HUB_CHAT'] = 'cli'
        os.environ['PATH'] = str(cls.fakebin) + ':' + os.environ['PATH']
        os.environ['OPENAI_API_KEY'] = 'test-key-must-not-reach-codex'
        os.environ['TERM'] = 'xterm-256color'
        os.environ.pop('TMUX', None)
        config = {'schemaVersion': 1, 'defaultAccount': '1', 'accounts': {slot: {'label': label, 'description': 'Demo workspace', 'home': str(cls.root / slot), 'session': 'codex-sub-' + slot} for slot, label in getattr(cls, 'FIXTURE_LABELS', [('1', 'One'), ('2', 'Two'), ('3', 'Three')])}}
        (cls.root / 'config.json').write_text(json.dumps(config))
        hub.reload_config()
        for slot in hub.LABELS:
            (cls.root / slot).mkdir()
            with closing(sqlite3.connect(cls.root / slot / 'state_5.sqlite')) as db, db:
                db.execute('CREATE TABLE threads(id TEXT, title TEXT, cwd TEXT, archived INT, '
                           'has_user_event INT, updated_at INT)')
                db.execute('INSERT INTO threads VALUES(?,?,?,0,1,1)',
                           (f'00000000-0000-0000-0000-00000000000{slot}', f'Saved in {slot}', str(cls.project)))
        hub.setup()
        for window in hub.windows():
            hub.tmux('set-option', '-w', '-t', window['id'], 'remain-on-exit', 'on')
        cls.output = b''
        cls.child, cls.fd = pty.fork()
        if cls.child == 0:
            os.execvp('tmux', ['tmux', '-S', str(hub.SOCKET), 'attach-session', '-t', 'codex-sub-1'])
        fcntl.ioctl(cls.fd, termios.TIOCSWINSZ, struct.pack('HHHH', 40, 140, 0, 0))
        cls.wait_for(lambda: hub.tmux('display-message', '-p', '-t', 'codex-sub-1:', '#{window_width}') == '140')
        cls.wait_for(lambda: 'Codex' in cls.sidebar_text('1'))
        cls.wait_for(lambda: int(hub.tmux('display-message', '-p', '-t', cls.account_window('1')['sidebar'], '#{pane_width}')) == 36)

    @classmethod
    def tearDownClass(cls):
        hub.tmux('kill-server', check=False)
        os.close(cls.fd)
        os.waitpid(cls.child, 0)
        os.environ.clear()
        os.environ.update(cls.oldenv)
        cls.scratch.cleanup()

    @classmethod
    def pump(cls):
        while select.select([cls.fd], [], [], 0)[0]:
            try:
                cls.output += os.read(cls.fd, 65536)
            except OSError:
                break

    @classmethod
    def wait_for(cls, predicate, timeout=8):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            cls.pump()
            if predicate():
                return
            time.sleep(.08)
        print(hub.tmux('list-panes', '-a', '-F', '#{session_name} #{pane_id} #{pane_left} #{pane_top} #{pane_width} #{pane_height} mouse=#{mouse_any_flag} active=#{pane_active}'))
        print(cls.sidebar_text('1'))
        print(cls.sidebar_text('2'))
        print(hub.state())
        if hasattr(cls, 'chat'):
            print(hub.tmux('capture-pane', '-p', '-t', cls.chat['pane'], check=False))
        home = next(w for w in hub.windows() if w['slot'] == '2' and w['kind'] == 'home')
        print(hub.tmux('capture-pane', '-p', '-t', home['pane']))
        raise AssertionError('Timed out waiting for UI state')

    @classmethod
    def account_window(cls, slot):
        active = hub.tmux('display-message', '-p', '-t', f'codex-sub-{slot}:', '#{window_id}')
        return next(w for w in hub.windows() if w['id'] == active)

    @classmethod
    def sidebar_text(cls, slot):
        pane = cls.account_window(slot)['sidebar']
        return hub.tmux('capture-pane', '-p', '-t', pane)

    @classmethod
    def click(cls, x, y):
        # SGR mouse coordinates are one-based terminal coordinates.
        os.write(cls.fd, f'\x1b[<0;{x};{y}M'.encode())
        time.sleep(.05)
        os.write(cls.fd, f'\x1b[<0;{x};{y}m'.encode())
        # Give the frontend a frame to consume the release before typing or
        # measuring another control; hosted runners can schedule it later.
        time.sleep(.15)
        cls.pump()

    @classmethod
    def sidebar_click(cls, slot, x, y):
        pane = cls.account_window(slot)['sidebar']
        left, top = map(int, hub.tmux('display-message', '-p', '-t', pane,
                                    '#{pane_left} #{pane_top}').split())
        cls.click(left + x + 1, top + y + 2)

    def test_mouse_workflow_and_isolation(self):
        # Click second account tab while the main terminal still has focus.
        pane = self.account_window('1')['sidebar']
        width = int(hub.tmux('display-message', '-p', '-t', pane, '#{pane_width}'))
        tabsize = max(5, (width - 4) // 3)
        self.wait_for(lambda: self.sidebar_text('1').splitlines()[2][2 + tabsize:1 + 2 * tabsize].strip() == 'Two')
        self.sidebar_click('1', 3 + tabsize, 3)
        self.wait_for(lambda: hub.tmux('list-clients', '-F', '#{session_name}') == 'codex-sub-2')
        self.wait_for(lambda: 'Projects' in self.sidebar_text('2'))
        # History is isolated, and clicking a saved chat resumes that exact account/thread.
        self.assertIn('Saved in 2', self.sidebar_text('2'))
        self.assertNotIn('Saved in 1', self.sidebar_text('2'))
        self.sidebar_click('2', 8, 13)
        self.wait_for(lambda: (self.root / '2/invoked.json').exists())
        invoked = json.loads((self.root / '2/invoked.json').read_text())
        self.assertEqual(invoked['home'], str(self.root / '2'))
        self.assertEqual(invoked['cwd'], str(self.project))
        self.assertIsNone(invoked['api'])
        self.assertEqual(invoked['args'][:2], ['resume', '00000000-0000-0000-0000-000000000002'])
        self.wait_for(lambda: any(w['kind'] == 'chat' and w['pane'] and w['sidebar'] for w in hub.windows()))
        resumed = next(w for w in hub.windows() if w['kind'] == 'chat')
        self.wait_for(lambda: self.account_window('2')['id'] == resumed['id'])
        original_pid = hub.tmux('display-message', '-p', '-t', resumed['pane'], '#{pane_pid}')
        self.wait_for(lambda: 'Saved in 2' in self.sidebar_text('2'))
        # Click New chat; the previous Codex process must keep running.
        self.sidebar_click('2', 10, 6)
        self.wait_for(lambda: len([w for w in hub.windows() if w['kind'] == 'chat']) == 2)
        self.wait_for(lambda: self.account_window('2')['id'] != resumed['id'])
        self.wait_for(lambda: 'New chat' in self.sidebar_text('2'))
        self.assertEqual(original_pid, hub.tmux('display-message', '-p', '-t', resumed['pane'], '#{pane_pid}'))
        self.assertEqual(hub.tmux('display-message', '-p', '-t', resumed['pane'], '#{pane_dead}'), '0')
        # New chat is second live row. Click original and verify switch, not duplicate resume.
        self.sidebar_click('2', 8, 13)
        self.wait_for(lambda: self.account_window('2')['id'] == resumed['id'])
        self.assertEqual(len([w for w in hub.windows() if w['kind'] == 'chat']), 2)
        # Clicking folder collapses/expands its chats.
        self.sidebar_click('2', 8, 12)
        self.wait_for(lambda: 'Saved in 2' not in self.sidebar_text('2'))
        self.sidebar_click('2', 8, 12)
        self.wait_for(lambda: 'Saved in 2' in self.sidebar_text('2'))
        # Setup is repeatable and upgrading sidebars preserves every chat PID.
        before = {w['id']: w['pane'] for w in hub.windows()}
        hub.setup(reload=True)
        self.assertEqual(before, {w['id']: w['pane'] for w in hub.windows()})
        self.assertEqual(original_pid, hub.tmux('display-message', '-p', '-t', resumed['pane'], '#{pane_pid}'))
        self.assertEqual(hub.tmux('display-message', '-p', '-t', resumed['pane'], '#{pane_dead}'), '0')

        # Open the project picker and create a folder entirely with visible controls.
        self.wait_for(lambda: 'Projects' in self.sidebar_text('2'))
        type(self).output = b''
        self.sidebar_click('2', 26, 10)
        self.wait_for(lambda: b'Open project' in type(self).output)
        # Centered popup is 119 x 34 with a one-cell border in a 140 x 40 terminal.
        def popup_click(x, y):
            self.click(x + 12, y + 4)
        def chat_popup_click(x, y):
            # Popup centering differs between tmux versions. Read the rendered
            # title's cursor position rather than assuming a fixed top margin.
            output = type(self).output.decode(errors='replace')
            title = output.rfind('Chat options')
            positions = list(re.finditer(r'\x1b\[(\d+);(\d+)H', output[:title]))
            last = positions[-1]
            prefix = re.sub(r'\x1b\[[0-9;?]*[A-Za-z]|\x1b\([AB0]', '', output[last.end():title])
            row, column = map(int, last.groups())
            print('Popup target:', row, column, repr(prefix), x, y)
            self.click(x + column + len(prefix) - 3, y + row - 2)
        popup_click(6, 6)
        os.write(self.fd, str(self.project).encode())
        popup_click(109, 6)  # Go
        self.wait_for(lambda: b'New folder' in type(self).output)
        popup_click(108, 8)
        self.wait_for(lambda: b'Create' in type(self).output)
        os.write(self.fd, b'Made by mouse')
        popup_click(107, 27)
        created = self.project / 'Made by mouse'
        self.wait_for(created.is_dir)
        popup_click(103, 29)  # Open project
        self.wait_for(lambda: hub.state().get('selected', {}).get('2') == str(created))
        self.wait_for(lambda: 'Made by mouse' in self.sidebar_text('2'))
        self.sidebar_click('2', 10, 6)
        self.wait_for(lambda: json.loads((self.root / '2/invoked.json').read_text())['cwd'] == str(created))
        self.assertEqual(hub.tmux('display-message', '-p', '-t', resumed['pane'], '#{pane_dead}'), '0')
        self.wait_for(lambda: self.account_window('2')['path'] == str(created))
        self.wait_for(lambda: self.account_window('2')['pane'] and self.account_window('2')['sidebar'])
        self.wait_for(lambda: 'Made by mouse' in self.sidebar_text('2') and 'New chat' in self.sidebar_text('2'))
        self.wait_for(lambda: 'No chats yet' not in self.sidebar_text('2'))
        newest = self.account_window('2')
        def chat_menu(label):
            capture = subprocess.run(['tmux', '-S', str(hub.SOCKET), 'capture-pane', '-p', '-t',
                                      self.account_window('2')['sidebar']], text=True, capture_output=True, check=True).stdout
            lines = capture.splitlines()
            folder = next(i for i, line in enumerate(lines) if 'Made by mouse' in line)
            row = next(i for i in range(folder + 1, len(lines)) if label in lines[i] and '···' in lines[i])
            self.sidebar_click('2', lines[row].index('···') + 1, row)
        type(self).output = b''
        chat_menu('New chat')
        self.wait_for(lambda: b'Chat options' in type(self).output)
        chat_popup_click(8, 6)
        os.write(self.fd, b'\x15Renamed by mouse')
        time.sleep(.25)
        chat_popup_click(10, 8)
        try:
            self.wait_for(lambda: any(w['id'] == newest['id'] and w['name'] == 'Renamed by mouse' for w in hub.windows()))
        except AssertionError:
            print('Rename target:', newest['id'], [(w['id'], w['name']) for w in hub.windows()])
            print('Popup input tail:', repr(type(self).output[-1800:]))
            raise
        self.wait_for(lambda: 'Renamed by mouse' in self.sidebar_text('2'))
        type(self).output = b''
        chat_menu('Renamed by mouse')
        self.wait_for(lambda: b'Chat options' in type(self).output)
        chat_popup_click(12, 13)
        self.wait_for(lambda: b'Confirm close' in type(self).output)
        chat_popup_click(12, 13)
        self.wait_for(lambda: all(w['id'] != newest['id'] for w in hub.windows()))
        self.assertEqual(hub.tmux('display-message', '-p', '-t', resumed['pane'], '#{pane_dead}'), '0')
        # The home composer sends its text to the selected account and project.
        self.wait_for(lambda: self.account_window('2')['kind'] == 'home')
        home = self.account_window('2')
        self.wait_for(lambda: 'Ask Codex' in hub.tmux('capture-pane', '-p', '-t', home['pane']))
        left, top = map(int, hub.tmux('display-message', '-p', '-t', home['pane'],
                                     '#{pane_left} #{pane_top}').split())
        self.click(left + 21, top + 19)
        prompt = 'Explain this project;\nkeep $HOME literal'
        os.write(self.fd, prompt.encode())
        self.wait_for(lambda: all(line in hub.tmux('capture-pane', '-p', '-t', home['pane']) for line in prompt.splitlines()))
        self.click(left + 78, top + 23)
        self.wait_for(lambda: json.loads((self.root / '2/invoked.json').read_text())['args'][-1] == prompt)
        launched = json.loads((self.root / '2/invoked.json').read_text())
        self.assertEqual(launched['args'][-2], '--')
        self.assertEqual(launched['cwd'], str(created))
        self.assertEqual(launched['home'], str(self.root / '2'))
        self.assertEqual(hub.tmux('display-message', '-p', '-t', resumed['pane'], '#{pane_dead}'), '0')
        self.wait_for(lambda: self.account_window('2')['kind'] == 'chat')
        self.assertEqual(self.account_window('2')['name'], prompt.splitlines()[0])
        # The same visible controls remain usable in a normal 80 x 24 terminal.
        fcntl.ioctl(self.fd, termios.TIOCSWINSZ, struct.pack('HHHH', 24, 80, 0, 0))
        self.wait_for(lambda: int(hub.tmux('display-message', '-p', '-t', self.account_window('2')['sidebar'], '#{pane_width}')) == 26)
        self.wait_for(lambda: '+ Add project' in self.sidebar_text('2'))
        self.assertIn('Search chats', self.sidebar_text('2'))


if __name__ == '__main__':
    unittest.main()
