"""Enter dispatch, inline queue controls and modified-Enter/paste handling."""
import json
import os
import time
import test_native
from test_hub import hub


class EnterQueue(test_native.NativeIntegration):
    def test_mouse_workflow_and_isolation(self):
        hub.new_chat('1', self.project)
        type(self).chat = self.account_window('1')
        self.wait_for(lambda: 'fixture-sol' in self.capture() and 'Connecting' not in self.capture())
        self.click_text('Message Codex')
        os.write(self.fd, b'Enter starts a turn\r')
        self.wait_for(lambda: len([r for r in self.rpc() if r.get('method') == 'turn/start']) == 1)
        self.wait_for(lambda: 'Message Codex' in self.capture())
        time.sleep(.85)
        os.write(self.fd, b'Queued first\r')
        self.wait_for(lambda: 'Queue 1' in self.capture() and '↳ Steer' in self.capture())
        self.wait_for(lambda: 'Message Codex' in self.capture())
        time.sleep(.85)
        os.write(self.fd, b'Queued second\r')
        self.wait_for(lambda: 'Queue 2' in self.capture())
        self.assertLess(self.capture().index('Queued first'), self.capture().index('Queued second'))
        ident = hub.tmux('show-option', '-wv', '-t', self.chat['id'], '@hub_thread')
        saved = self.root / 'tui-state/1' / (ident + '.json')
        self.assertEqual(len(json.loads(saved.read_text())['queues']['1:' + ident]), 2)
        # Second Enter sends the full queue into the active turn, without replay.
        os.write(self.fd, b'\r')
        self.wait_for(lambda: any(r.get('method') == 'turn/steer' for r in self.rpc()))
        steer = [r for r in self.rpc() if r.get('method') == 'turn/steer'][-1]
        self.assertEqual(steer['params']['input'][0]['text'], 'Queued first\n\nQueued second')
        self.wait_for(lambda: 'Queue 1' not in self.capture() and 'Queue 2' not in self.capture())
        time.sleep(.85)
        # Two Enter presses in the same write must not race the asynchronous send.
        os.write(self.fd, b'Rapid message\r\r')
        self.wait_for(lambda: len([r for r in self.rpc() if r.get('method') == 'turn/steer']) == 2)
        self.assertEqual([r for r in self.rpc() if r.get('method') == 'turn/steer'][-1]['params']['input'][0]['text'], 'Rapid message')
        self.wait_for(lambda: 'Message Codex' in self.capture())
        # Pasted newlines must remain in the draft until Enter is deliberately pressed.
        os.write(self.fd, b'\x1b[200~Pasted first\nPasted second\x1b[201~')
        self.wait_for(lambda: json.loads(saved.read_text())['draft']['text'] == 'Pasted first\nPasted second')
        self.assertEqual(len([r for r in self.rpc() if r.get('method') == 'turn/steer']), 2)
        os.write(self.fd, b'\x15Modified first\x1b\rModified second')
        self.wait_for(lambda: json.loads(saved.read_text())['draft']['text'] == 'Modified first\nModified second')
        os.write(self.fd, b'\r')
        self.wait_for(lambda: 'Queue 1' in self.capture())
        # Delete an inline queue entry with its visible icon.
        lines = self.capture().splitlines()
        y = next(i for i, line in enumerate(lines) if '↳ Steer' in line)
        self.chat_click(lines[y].index('×'), y)
        self.wait_for(lambda: 'Queue 1' not in self.capture() and 'Queue 2' not in self.capture())
        self.click_text('Message Codex')
        os.write(self.fd, b'Click to steer\r')
        self.wait_for(lambda: '↳ Steer' in self.capture())
        self.click_text('↳ Steer')
        self.wait_for(lambda: len([r for r in self.rpc() if r.get('method') == 'turn/steer']) == 3)
        self.assertEqual([r for r in self.rpc() if r.get('method') == 'turn/steer'][-1]['params']['input'][0]['text'], 'Click to steer')
