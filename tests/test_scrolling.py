"""Check reading-position stability, real wheel input, drag scroll and resize."""
import fcntl
import json
import os
import struct
import termios
import time
import test_native
from test_hub import hub


class ScrollingIntegration(test_native.NativeIntegration):
    def test_mouse_workflow_and_isolation(self):
        reply = '\n\n'.join(f'Paragraph {n:03d}. Read this sentence while more output arrives.' for n in range(1, 91)) + '\n\nEND OF RESPONSE'
        (self.root / '1/reply.md').write_text(reply)
        hub.new_chat('1', self.project)
        type(self).chat = self.account_window('1')
        self.wait_for(lambda: 'fixture-sol' in self.capture() and 'Connecting' not in self.capture())
        self.send_text('A long response for scrolling')
        self.wait_for(lambda: 'END OF RESPONSE' in self.capture())
        left, top = map(int, hub.tmux('display-message', '-p', '-t', self.chat['pane'], '#{pane_left} #{pane_top}').split())
        for _ in range(9):
            os.write(self.fd, f'\x1b[<64;{left+20};{top+15}M'.encode())
        self.wait_for(lambda: 'END OF RESPONSE' not in self.capture())
        before = self.capture().splitlines()[5:10]
        (self.root / '1/control.json').write_text(json.dumps({'action': 'append', 'text': '\n\nFresh streamed output'}))
        self.wait_for(lambda: not (self.root / '1/control.json').exists())
        time.sleep(.2)
        self.assertEqual(before, self.capture().splitlines()[5:10], 'Streaming moved the reading position')
        # A click/drag on the scrollbar reaches old history.
        pane_width = int(hub.tmux('display-message', '-p', '-t', self.chat['pane'], '#{pane_width}'))
        track_x = left + pane_width - 1
        os.write(self.fd, f'\x1b[<35;{track_x};{top+16}M'.encode())
        time.sleep(.1)
        self.assertEqual(before, self.capture().splitlines()[5:10], 'Hovering the scrollbar scrolled the chat')
        os.write(self.fd, f'\x1b[<0;{track_x};{top+25}M'.encode())
        os.write(self.fd, f'\x1b[<32;{track_x};{top+7}M'.encode())
        os.write(self.fd, f'\x1b[<0;{track_x};{top+7}m'.encode())
        self.wait_for(lambda: 'Paragraph 001' in self.capture())
        # Resize preserves the same item and reading area rather than returning to the tail.
        fcntl.ioctl(self.fd, termios.TIOCSWINSZ, struct.pack('HHHH', 30, 100, 0, 0))
        self.wait_for(lambda: int(hub.tmux('display-message', '-p', '-t', self.chat['pane'], '#{pane_width}')) < pane_width)
        self.wait_for(lambda: 'Paragraph 001' in self.capture())
        self.assertNotIn('Fresh streamed output', self.capture())
        # Jump to latest resumes automatic following.
        self.click_text('↓')
        self.wait_for(lambda: 'Fresh streamed output' in self.capture())
        (self.root / '1/control.json').write_text(json.dumps({'action': 'append', 'text': '\n\nFollowing again'}))
        self.wait_for(lambda: 'Following again' in self.capture())
