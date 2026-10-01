"""A never-sent draft has no Codex rollout; restart must recover its composer."""
import json
import os
import test_native
from test_hub import hub


class DraftRecovery(test_native.NativeIntegration):
    def test_mouse_workflow_and_isolation(self):
        hub.new_chat('1', self.project)
        type(self).chat = self.account_window('1')
        self.wait_for(lambda: next(w for w in hub.windows() if w['id'] == self.chat['id'])['busy'] == '0')
        old = hub.tmux('show-option', '-wv', '-t', self.chat['id'], '@hub_thread')
        self.click_text('Message Codex')
        os.write(self.fd, b'Keep this unsent draft')
        saved = self.root / 'tui-state/1' / (old + '.json')
        self.wait_for(lambda: json.loads(saved.read_text())['draft']['text'] == 'Keep this unsent draft')
        self.wait_for(lambda: 'Draft' in self.sidebar_text('1'))
        self.assertNotIn('New chat', '\n'.join(self.sidebar_text('1').splitlines()[12:-6]))
        window = next(w for w in hub.windows() if w['id'] == self.chat['id'])
        hub.reload_chat(window)
        self.wait_for(lambda: hub.tmux('show-option', '-wv', '-t', self.chat['id'], '@hub_thread') != old)
        self.wait_for(lambda: 'Keep this unsent draft' in self.capture())
        self.wait_for(lambda: next(w for w in hub.windows() if w['id'] == self.chat['id'])['busy'] == '0')
        self.assertNotIn('thread not loaded', self.capture())
        new = hub.tmux('show-option', '-wv', '-t', self.chat['id'], '@hub_thread')
        self.assertNotIn(old, hub.state()['chats']['1'])
        self.assertIn(new, hub.state()['chats']['1'])
        self.assertFalse(saved.exists())
        # Recovery creates a thread, not a model turn; only the user's Enter sends.
        self.assertFalse(any(r.get('method') == 'turn/start' for r in self.rpc()))
        self.click_text('Keep this unsent draft')
        os.write(self.fd, b'\r')
        self.wait_for(lambda: any(r.get('method') == 'turn/start' for r in self.rpc()))
        turns = [r for r in self.rpc() if r.get('method') == 'turn/start']
        self.assertEqual(turns[0]['params']['input'][0]['text'], 'Keep this unsent draft')
