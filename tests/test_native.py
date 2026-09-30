"""Mouse checks of the native chat through real tmux and a fake stdio server."""
import fcntl
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import termios
import time
import test_hub
from test_hub import REPO, hub


class NativeIntegration(test_hub.HubIntegration):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        shutil.copyfile(REPO / 'tests/fake_codex.py', cls.fakebin / 'codex')
        os.environ.pop('CODEX_HUB_CHAT', None)
        hub.tmux('set-environment', '-gu', 'CODEX_HUB_CHAT')
        for slot in hub.LABELS:
            hub.tmux('set-environment', '-u', '-t', hub.account_session(slot), 'CODEX_HUB_CHAT')
        hub.setup(reload=True)
        # Opening links is recorded, so the test never opens a real browser.
        for name in ('open', 'xdg-open', 'qlmanage'):
            fake = cls.fakebin / name
            fake.write_text('#!/usr/bin/env python3\nimport os,sys,json\nfrom pathlib import Path\n'
                            'Path(os.environ["CODEX_HOME"]).joinpath("opened.json").write_text(json.dumps(sys.argv[1:]))\n')
            fake.chmod(0o700)

    @classmethod
    def capture(cls):
        return subprocess.run(['tmux', '-S', str(hub.SOCKET), 'capture-pane', '-p', '-t', cls.chat['pane']], text=True, capture_output=True, check=True).stdout

    @classmethod
    def chat_click(cls, x, y):
        left, top = map(int, hub.tmux('display-message', '-p', '-t', cls.chat['pane'], '#{pane_left} #{pane_top}').split())
        cls.click(left + x + 1, top + y + 2)

    @classmethod
    def click_text(cls, label):
        try:
            cls.wait_for(lambda: label in cls.capture())
        except AssertionError:
            print('CHAT CAPTURE:', cls.capture())
            raise
        for y, line in enumerate(cls.capture().splitlines()):
            if label in line:
                cls.chat_click(line.index(label) + 1, y)
                return
        raise AssertionError(label)

    @classmethod
    def rpc(cls):
        path = cls.root / '1/rpc.jsonl'
        return [json.loads(v) for v in path.read_text().splitlines()] if path.exists() else []

    @classmethod
    def send_text(cls, text):
        cls.click_text('Message Codex')
        os.write(cls.fd, text.encode())
        cls.wait_for(lambda: text in cls.capture())
        cls.click_text('↑')
        cls.wait_for(lambda: 'Message Codex' in cls.capture())

    def test_mouse_workflow_and_isolation(self):
        hub.new_chat('1', self.project)
        type(self).chat = self.account_window('1')
        self.wait_for(lambda: 'fixture-sol' in self.capture() and 'Connecting' not in self.capture())
        self.assertEqual(hub.tmux('show-option', '-wv', '-t', self.chat['id'], '@hub_engine'), 'tui')
        self.send_text('First message')
        self.wait_for(lambda: 'Fixture response' in self.capture())
        self.wait_for(lambda: next(w for w in hub.windows() if w['id'] == self.chat['id'])['busy'] == '1')
        with self.assertRaises(ValueError):
            hub.reload_chat(next(w for w in hub.windows() if w['id'] == self.chat['id']), force=True)
        self.click_text('Open docs')
        self.wait_for(lambda: (self.root / '1/opened.json').exists())
        self.assertEqual(json.loads((self.root / '1/opened.json').read_text()), ['https://example.com/docs'])
        self.send_text('Queued message')
        self.wait_for(lambda: '≡ 1' in self.capture())
        self.click_text('≡ 1')
        self.click_text('Queued message')
        self.click_text('Edit text')
        self.chat_click(5, 5)
        os.write(self.fd, b'\x15Edited queue')
        self.click_text('Save')
        self.wait_for(lambda: 'Message Codex' in self.capture())
        ident = hub.tmux('show-option', '-wv', '-t', self.chat['id'], '@hub_thread')
        saved = self.root / 'tui-state/1' / (ident + '.json')
        self.wait_for(lambda: json.loads(saved.read_text())['queues']['1:' + ident][0]['text'] == 'Edited queue')
        # Complete first fixture turn. Only then may the edited message dispatch.
        (self.root / '1/control.json').write_text(json.dumps({'action': 'complete'}))
        self.wait_for(lambda: len([r for r in self.rpc() if r.get('method') == 'turn/start']) == 2)
        turns = [r for r in self.rpc() if r.get('method') == 'turn/start']
        self.assertEqual(turns[1]['params']['input'][0]['text'], 'Edited queue')
        self.click_text('Message Codex')
        os.write(self.fd, b'/model\n')
        self.click_text('Fixture Luna')
        self.wait_for(lambda: 'fixture-luna' in self.capture())
        self.click_text('high ▾')
        self.click_text('medium')
        self.wait_for(lambda: 'medium ▾' in self.capture())
        # Explicit approval button; no automatic response.
        (self.root / '1/control.json').write_text(json.dumps({'action': 'approval'}))
        self.click_text('Respond (1)')
        self.assertIn('echo fixture', self.capture())
        self.click_text('Decline')
        self.wait_for(lambda: any(r.get('id') == 123 and r.get('result', {}).get('decision') == 'decline' for r in self.rpc()))
        self.click_text('◇ Ask approval')
        self.click_text('Approve for me')
        self.wait_for(lambda: '◇ Approve for me' in self.capture())
        self.click_text('◔')
        self.wait_for(lambda: '15,000 / 128,000' in self.capture())
        self.click_text('Back')
        self.click_text('ⓘ')
        self.click_text('Pin chat')
        self.wait_for(lambda: ident in hub.state().get('pins', {}).get('1', []))
        self.wait_for(lambda: 'Pinned' in self.sidebar_text('1'))
        self.click_text('ⓘ')
        # Inline thumbnail and image input use local files.
        from PIL import Image
        sample = self.project / 'sample.png'
        Image.new('RGB', (48, 32), '#3c7099').save(sample)
        self.click_text('+')
        self.click_text('sample.png')
        self.click_text('▧ 1')
        self.click_text('sample.png')
        self.click_text('Preview')
        self.wait_for(lambda: 'terminal thumbnail' in self.capture())
        self.click_text('Back')
        self.click_text('↑')
        self.wait_for(lambda: any(m['images'] for m in json.loads(saved.read_text())['queues']['1:' + ident]))
        # Capture fixture terminal for visual review if requested by caller.
        output = os.environ.get('CODEX_HUB_PREVIEW')
        if output:
            from preview import render, color
            from PIL import ImageDraw, ImageFont
            picture = Image.new('RGB', (1400, 960), color(234))
            draw = ImageDraw.Draw(picture)
            fonts = [ImageFont.truetype('/System/Library/Fonts/Menlo.ttc', 16, index=i) for i in (0, 1)]
            for pane, bg in ((self.chat['sidebar'], 233), (self.chat['pane'], 234)):
                x,y,w,h = map(int, hub.tmux('display-message', '-p', '-t', pane, '#{pane_left} #{pane_top} #{pane_width} #{pane_height}').split())
                render(draw, hub.tmux('capture-pane', '-e', '-p', '-t', pane), x*10, (y+1)*24, w,h,bg,fonts)
            Path(output).parent.mkdir(parents=True, exist_ok=True)
            picture.save(output)
        # Stop pauses queue; compact controls remain reachable without overlap.
        self.wait_for(lambda: 'Working on your action' not in self.capture())
        self.click_text('■')
        self.wait_for(lambda: 'Queue paused' in self.capture())
        fcntl.ioctl(self.fd, termios.TIOCSWINSZ, struct.pack('HHHH', 24, 80, 0, 0))
        self.wait_for(lambda: int(hub.tmux('display-message', '-p', '-t', self.chat['sidebar'], '#{pane_width}')) == 26)
        self.click_text('fixture-luna')
        self.click_text('Fixture Sol')
        self.click_text('☰')
        self.wait_for(lambda: int(hub.tmux('display-message', '-p', '-t', self.chat['sidebar'], '#{pane_width}')) == 1)
        self.click_text('☰')
        self.wait_for(lambda: int(hub.tmux('display-message', '-p', '-t', self.chat['sidebar'], '#{pane_width}')) == 26)
        self.click_text('▣')
        self.wait_for(lambda: hub.tmux('display-message', '-p', '-t', self.chat['pane'], '#{pane_in_mode}') == '1')
        hub.tmux('send-keys', '-X', '-t', self.chat['pane'], 'cancel')
        self.wait_for(lambda: hub.tmux('display-message', '-p', '-t', self.chat['pane'], '#{pane_in_mode}') == '0')
        time.sleep(.2)
        self.click_text('Message Codex')
        os.write(self.fd, b'A persistent draft')
        self.wait_for(lambda: json.loads(saved.read_text())['draft']['text'] == 'A persistent draft')
        hub.tmux('kill-server')
        os.close(self.fd)
        os.waitpid(self.child, 0)
        hub.setup()
        hub.restore_chats()
        import pty
        child, fd = pty.fork()
        if child == 0:
            os.execvp('tmux', ['tmux', '-S', str(hub.SOCKET), 'attach-session', '-t', 'codex-sub-1'])
        type(self).child, type(self).fd = child, fd
        fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack('HHHH', 40, 140, 0, 0))
        type(self).chat = next(w for w in hub.windows() if w['thread'] == ident)
        hub.focus(self.chat)
        self.wait_for(lambda: hub.tmux('display-message', '-p', '-t', self.chat['pane'], '#{pane_width} #{pane_height}') == '103 39')
        self.wait_for(lambda: 'A persistent draft' in self.capture())
        self.wait_for(lambda: 'Connecting' not in self.capture())
        self.wait_for(lambda: 'Thinking' in self.capture())
        self.assertTrue(json.loads(saved.read_text())['paused']['1:' + ident])
        self.click_text('Thinking')
        self.wait_for(lambda: 'Checking the project structure' in self.capture())
        self.click_text('Thinking')
        # Reconnect this same completed chat to the upgraded frontend.
        self.wait_for(lambda: next(w for w in hub.windows() if w['id'] == self.chat['id'])['busy'] == '0')
        before_reload = hub.tmux('display-message', '-p', '-t', self.chat['pane'], '#{pane_pid}')
        hub.reload_chat(next(w for w in hub.windows() if w['id'] == self.chat['id']))
        self.wait_for(lambda: 'A persistent draft' in self.capture() and 'Connecting' not in self.capture())
        self.assertNotEqual(before_reload, hub.tmux('display-message', '-p', '-t', self.chat['pane'], '#{pane_pid}'))
        self.assertEqual(hub.tmux('show-option', '-wv', '-t', self.chat['id'], '@hub_version'), hub.hub_config.VERSION)
        self.click_text('A persistent draft')
        os.write(self.fd, b'\x15/permissions\n')
        self.wait_for(lambda: 'Approval mode · next turn' in self.capture())
        self.click_text('Approve for me')
        self.wait_for(lambda: '◇ Approve for me' in self.capture())
        original_pid = hub.tmux('display-message', '-p', '-t', self.chat['pane'], '#{pane_pid}')
        hub.hub_config.add('work', label='Work', root=self.root)
        hub.reload_config()
        hub.setup()
        hub.new_chat('work', self.project, background=True)
        self.wait_for(lambda: (self.root / 'accounts/work/rpc.jsonl').exists())
        self.assertEqual(original_pid, hub.tmux('display-message', '-p', '-t', self.chat['pane'], '#{pane_pid}'))
        self.assertTrue(any(w['slot'] == 'work' for w in hub.windows()))
        self.assertFalse((self.root / '2/rpc.jsonl').exists())
        self.assertFalse((self.root / '3/rpc.jsonl').exists())
