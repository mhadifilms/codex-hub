"""Real mouse lifecycle: draft close, right-click, archive/restore and delete."""
import json
import os
import sqlite3
import subprocess
import time
import test_native
from test_hub import hub


class Lifecycle(test_native.NativeIntegration):
    @classmethod
    def sidebar_action(cls, label, right=False):
        position = None
        def locate():
            nonlocal position
            pane = cls.account_window('1')['sidebar']
            # Preserve the leading blank screen row when locating mouse targets.
            lines = subprocess.check_output(['tmux', '-S', str(hub.SOCKET), 'capture-pane', '-p', '-t', pane], text=True).splitlines()
            for y, line in enumerate(lines):
                if label in line:
                    left, top = map(int, hub.tmux('display-message', '-p', '-t', pane, '#{pane_left} #{pane_top}').split())
                    position = (left + line.index(label) + 2, top + y + 2)
                    return True
            return False
        cls.wait_for(locate)
        if right:
            x,y = position
            os.write(cls.fd, f'\x1b[<35;{x};{y}M'.encode())
            time.sleep(.1)
            os.write(cls.fd, f'\x1b[<2;{x};{y}M'.encode())
            time.sleep(.05)
            os.write(cls.fd, f'\x1b[<2;{x};{y}m'.encode())
        else:
            cls.click(*position)

    def test_mouse_workflow_and_isolation(self):
        hub.new_chat('1', self.project)
        type(self).chat = self.account_window('1')
        self.wait_for(lambda: next(w for w in hub.windows() if w['id'] == self.chat['id'])['busy'] == '0')
        self.click_text('Message Codex')
        os.write(self.fd, b'Unsent draft')
        self.wait_for(lambda: 'Draft' in self.sidebar_text('1'))
        old_window = self.chat['id']
        self.click_text('×')
        self.wait_for(lambda: all(w['id'] != old_window for w in hub.windows()))
        self.wait_for(lambda: 'Draft' not in self.sidebar_text('1'))
        hub.restore_chats()
        self.assertTrue(all(w['id'] != old_window and w['kind'] != 'chat' for w in hub.windows()))
        # Database exclusions must also exclude the saved-record fallback.
        with sqlite3.connect(self.root / '1/state_5.sqlite') as db:
            db.execute('INSERT INTO threads VALUES(?,?,?,1,1,2)', ('archived-fixture','Archived fixture',str(self.project)))
            db.execute('INSERT INTO threads VALUES(?,?,?,0,0,2)', ('empty-fixture','New chat',str(self.project)))
        hub.update_state(lambda data: data['chats']['1'].update({
            'archived-fixture': {'cwd':str(self.project),'title':'Archived fixture','has_content':True,'open':False},
            'empty-fixture': {'cwd':str(self.project),'title':'New chat','has_content':True,'open':False}}))
        self.assertFalse({'archived-fixture','empty-fixture'} & {r['id'] for r in hub.history('1')[0]})
        self.assertIn('archived-fixture', {r['id'] for r in hub.history('1', archived=True)[0]})

        hub.new_chat('1', self.project)
        type(self).chat = self.account_window('1')
        self.wait_for(lambda: next(w for w in hub.windows() if w['id'] == self.chat['id'])['busy'] == '0')
        self.send_text('Lifecycle review')
        ident = hub.tmux('show-option','-wv','-t',self.chat['id'],'@hub_thread')
        current = next(w for w in hub.windows() if w['id']==self.chat['id'])
        self.wait_for(lambda: '■' in self.capture())
        with self.assertRaises(ValueError):
            hub.change_chat('1', ident, 'archive', {**current,'busy':'1'})
        self.click_text('■')
        self.wait_for(lambda: next(w for w in hub.windows() if w['id']==self.chat['id'])['busy']=='0')
        before = hub.state()['chats']['1'][ident].copy()
        failure = self.root / '1/fail-lifecycle'
        failure.touch()
        with self.assertRaises(RuntimeError):
            hub.change_chat('1', ident, 'archive', next(w for w in hub.windows() if w['id']==self.chat['id']))
        failure.unlink()
        self.assertEqual(hub.state()['chats']['1'][ident], before)
        self.sidebar_action('Lifecycle review', right=True)
        self.sidebar_action('Pin chat')
        self.wait_for(lambda: ident in hub.state().get('pins',{}).get('1',[]))
        self.sidebar_action('Lifecycle review', right=True)
        self.sidebar_action('Archive chat')
        self.wait_for(lambda: all(w['id']!=current['id'] for w in hub.windows()))
        self.assertTrue(hub.state()['chats']['1'][ident]['archived'])
        self.assertNotIn(ident,{r['id'] for r in hub.history('1')[0]})
        self.sidebar_action('Archived chats')
        self.sidebar_action('Lifecycle review', right=True)
        self.sidebar_action('Restore chat')
        self.wait_for(lambda: not hub.state()['chats']['1'][ident]['archived'])
        self.sidebar_action('All chats')
        self.sidebar_action('Lifecycle review')
        self.wait_for(lambda: self.account_window('1')['kind'] == 'chat')
        type(self).chat = self.account_window('1')
        self.wait_for(lambda: next(w for w in hub.windows() if w['id']==self.chat['id'])['busy']=='0')
        self.wait_for(lambda: 'Fixture response' in self.capture())
        # Delete requires confirmation; cancelling must retain the conversation.
        self.sidebar_action('Lifecycle review', right=True)
        self.sidebar_action('Delete chat…')
        self.wait_for(lambda: b'Confirm delete' in type(self).output)
        os.write(self.fd,b'\x1b')
        self.wait_for(lambda: 'Fixture response' in self.capture())
        self.assertFalse(hub.state()['chats']['1'][ident].get('deleted'))
        type(self).output = b''
        self.sidebar_action('Lifecycle review', right=True)
        self.sidebar_action('Delete chat…')
        self.wait_for(lambda: b'Confirm delete' in type(self).output)
        self.click(24,25)
        self.wait_for(lambda: hub.state()['chats']['1'][ident].get('deleted'))
        self.wait_for(lambda: all(w['id']!=self.chat['id'] for w in hub.windows()))
        self.assertNotIn(ident,{r['id'] for r in hub.history('1')[0]+hub.history('1',archived=True)[0]})
        self.assertFalse((self.root/'tui-state/1'/(ident+'.json')).exists())
        self.assertNotIn(ident,hub.state().get('pins',{}).get('1',[]))
        self.assertTrue(self.project.is_dir())
        self.assertTrue(any(r.get('method')=='thread/delete' and r['params']['threadId']==ident for r in self.rpc()))
