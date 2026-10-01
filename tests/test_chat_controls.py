"""Mouse regressions for draft editing, account navigation, usage and closing."""
import json
import os
import subprocess
import time
import test_native
from test_hub import hub


class ChatControls(test_native.NativeIntegration):
    def test_mouse_workflow_and_isolation(self):
        one = self.project / 'Only in One'
        two = self.project / 'Only in Two'
        one.mkdir()
        two.mkdir()
        hub.remember('1', one)
        hub.remember('2', two)
        hub.new_chat('1', one)
        type(self).chat = self.account_window('1')
        self.wait_for(lambda: 'fixture-sol' in self.capture() and 'Connecting' not in self.capture())
        self.wait_for(lambda: 'Only in One' in self.sidebar_text('1'))
        self.assertNotIn('Only in Two', self.sidebar_text('1'))
        self.assertNotIn('New chat', '\n'.join(self.sidebar_text('1').splitlines()[12:-6]))
        before = len(hub.windows())
        hub.new_chat('1', one)
        self.assertEqual(before, len(hub.windows()), 'Repeated New chat created another empty thread')
        self.send_text('Older chat')
        first = self.chat.copy()
        first_pid = hub.tmux('display-message', '-p', '-t', first['pane'], '#{pane_pid}')
        hub.new_chat('1', one)
        type(self).chat = self.account_window('1')
        self.wait_for(lambda: 'fixture-sol' in self.capture() and 'Connecting' not in self.capture())
        self.send_text('Newest chat')
        self.wait_for(lambda: 'Newest chat' in self.sidebar_text('1') and 'Older chat' in self.sidebar_text('1'))
        sidebar = self.sidebar_text('1')
        self.assertLess(sidebar.index('Newest chat'), sidebar.index('Older chat'))
        self.wait_for(lambda: '5h 77% · Week 62%' in self.sidebar_text('1'))
        self.click_text('☰')
        self.wait_for(lambda: hub.tmux('display-message', '-p', '-t', self.chat['sidebar'], '#{pane_width}') == '1')
        self.wait_for(lambda: '5h 77% · Week 62%' in self.capture())
        self.click_text('☰')
        self.wait_for(lambda: hub.tmux('display-message', '-p', '-t', self.chat['sidebar'], '#{pane_width}') == '36')
        self.wait_for(lambda: '■' in self.capture())
        self.assertNotIn('↑', self.capture(), 'Empty active composer should replace Send with Stop')
        ident = hub.tmux('show-option', '-wv', '-t', self.chat['id'], '@hub_thread')
        saved = self.root / 'tui-state/1' / (ident + '.json')
        self.click_text('Message Codex')
        os.write(self.fd, b'abcdef')
        self.wait_for(lambda: 'abcdef' in self.capture())
        footer = next(line for line in self.capture().splitlines() if '■' in line and '↑' in line)
        self.assertLess(footer.index('■'), footer.index('↑'))
        # Clicking inside the text places the caret at that character.
        lines = self.capture().splitlines()
        y = next(i for i, line in enumerate(lines) if 'abcdef' in line)
        x = lines[y].index('abcdef')
        self.chat_click(x + 3, y)
        os.write(self.fd, b'X')
        self.wait_for(lambda: json.loads(saved.read_text())['draft']['text'] == 'abcXdef')
        left, top = map(int, hub.tmux('display-message', '-p', '-t', self.chat['pane'], '#{pane_left} #{pane_top}').split())
        def drag(start, end, row):
            os.write(self.fd, f'\x1b[<35;{left+start+1};{top+row+2}M'.encode())
            os.write(self.fd, f'\x1b[<0;{left+start+1};{top+row+2}M'.encode())
            time.sleep(.08)
            os.write(self.fd, f'\x1b[<32;{left+end+1};{top+row+2}M'.encode())
            os.write(self.fd, f'\x1b[<0;{left+end+1};{top+row+2}m'.encode())
            time.sleep(.15)
            self.pump()
        drag(x + 1, x + 5, y)
        os.write(self.fd, b'Y')
        self.wait_for(lambda: json.loads(saved.read_text())['draft']['text'] == 'aYef')
        # Dragging transcript text highlights and copies the exact visible text.
        lines = self.capture().splitlines()
        y = next(i for i, line in enumerate(lines) if 'Fixture response.' in line)
        x = lines[y].index('Fixture response.')
        drag(x, x + 7, y)
        self.wait_for(lambda: (self.root / '1/copied.txt').exists())
        self.assertEqual((self.root / '1/copied.txt').read_text(), 'Fixture')
        # Account switch immediately selects that account's own project list.
        sidebar_pane = self.account_window('1')['sidebar']
        width = int(hub.tmux('display-message', '-p', '-t', sidebar_pane, '#{pane_width}'))
        self.sidebar_click('1', 3 + max(5, (width - 4) // 3), 3)
        self.wait_for(lambda: hub.tmux('list-clients', '-F', '#{session_name}') == hub.account_session('2'))
        self.wait_for(lambda: 'Only in Two' in self.sidebar_text('2'))
        self.assertNotIn('Only in One', self.sidebar_text('2'))
        self.sidebar_click('2', 3, 3)
        self.wait_for(lambda: hub.tmux('list-clients', '-F', '#{session_name}') == hub.account_session('1'))
        hub.focus(self.chat)
        # Close through the visible header control while the fake turn is active.
        wid = self.chat['id']
        self.click_text('×')
        self.wait_for(lambda: b'Chat options' in type(self).output)
        # Popup origin is fixed by this test's 140x40 terminal.
        self.click(24, 17)
        self.wait_for(lambda: b'Confirm close' in type(self).output)
        self.click(24, 17)
        self.wait_for(lambda: all(w['id'] != wid for w in hub.windows()))
        self.assertFalse(hub.state()['chats']['1'][ident]['open'])
        self.assertEqual(first_pid, hub.tmux('display-message', '-p', '-t', first['pane'], '#{pane_pid}'))
        self.assertIn('Newest chat', self.sidebar_text('1'), 'Closing must retain saved content')
        # Exit detaches only the UI; existing chats stay running.
        pane = self.account_window('1')['sidebar']
        height = int(hub.tmux('display-message', '-p', '-t', pane, '#{pane_height}'))
        self.sidebar_click('1', width // 2 + 3, height - 2)
        self.wait_for(lambda: not hub.tmux('list-clients', '-F', '#{session_name}'))
        self.assertEqual(hub.tmux('display-message', '-p', '-t', first['pane'], '#{pane_dead}'), '0')
