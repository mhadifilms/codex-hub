#!/usr/bin/env python3
"""Render a scripted native-TUI demo using isolated, synthetic data only."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import shutil
import sqlite3
import struct
import subprocess
import sys
import tempfile
import termios
import time
from PIL import Image, ImageDraw, ImageFont

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'tests'))
import test_native
from test_hub import hub
from preview import render, color


class Demo(test_native.NativeIntegration):
    FIXTURE_LABELS = [('1', 'Default')]

    @classmethod
    def wait_for(cls, predicate, timeout=12):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            cls.pump()
            if predicate():
                return
            time.sleep(.08)
        if hasattr(cls, 'chat'):
            print(cls.capture())
        raise AssertionError('Demo did not reach the expected UI state')


def font_pair():
    menlo = Path('/System/Library/Fonts/Menlo.ttc')
    if menlo.is_file():
        return [ImageFont.truetype(str(menlo), 16, index=i) for i in (0, 1)] + [
            ImageFont.truetype('/System/Library/Fonts/Apple Symbols.ttf', 20),
            ImageFont.truetype('/System/Library/Fonts/Supplemental/Arial Unicode.ttf', 16)]
    regular = '/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf'
    bold = '/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf'
    return [ImageFont.truetype(regular, 16), ImageFont.truetype(bold, 16)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path, help='Output MP4 path')
    parser.add_argument('--gif', type=Path, default=REPO / 'docs/demo.gif')
    parser.add_argument('--poster', type=Path)
    args = parser.parse_args()
    if not shutil.which('ffmpeg'):
        raise SystemExit('ffmpeg is required for the demo generator')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.gif.parent.mkdir(parents=True, exist_ok=True)
    fonts = font_pair()
    with tempfile.TemporaryDirectory(prefix='codex-hub-demo-frames-') as temporary:
        frames = Path(temporary)
        scene_list = []
        Demo.setUpClass()
        try:
            fcntl.ioctl(Demo.fd, termios.TIOCSWINSZ, struct.pack('HHHH', 45, 140, 0, 0))
            Demo.wait_for(lambda: hub.tmux('display-message', '-p', '-t', 'codex-sub-1:', '#{window_height}') == '44')
            website, service, notes = (Demo.root / name for name in ('Website', 'Service', 'Notes'))
            for project in (service, notes, website):
                project.mkdir()
                hub.remember('1', project)
            with sqlite3.connect(Demo.root / '1/state_5.sqlite') as db:
                db.execute('DELETE FROM threads')
                for ident, title, project in [('overview', 'Project overview', website), ('notes', 'Plan the next release', notes)]:
                    db.execute('INSERT INTO threads VALUES(?,?,?,0,1,?)', (ident, title, str(project), int(time.time())))
            hub.update_state(lambda data: data.update({'pins': {'1': ['overview']}}))
            (Demo.root / '1/demo-mode').touch()
            (Demo.root / '1/reply.md').write_text('## Project overview\n\nA **small web app** with *clear tests* and `app.py` as its entry point.\n\n```python\ndef greet(name):\n    return f"Hello, {name}!"\n```\n\n| Area | Status |\n| --- | --- |\n| UI | Ready |\n| Tests | Passing |\n\n[Read the docs](https://example.com/docs)')
            Demo.chat = Demo.account_window('1')
            Demo.wait_for(lambda: 'Website' in Demo.sidebar_text('1'))

            def record(caption, duration=2.4, poster=False):
                Demo.pump()
                picture = Image.new('RGB', (1480, 1200), '#101010')
                draw = ImageDraw.Draw(picture)
                draw.text((40, 17), 'Codex Hub  0.1.0', font=fonts[1], fill='#ececec')
                draw.text((1090, 17), 'Native terminal workspace', font=fonts[0], fill='#a5a5a5')
                for pane, background in ((Demo.chat['sidebar'], 234), (Demo.chat['pane'], 233)):
                    x, y, w, h = map(int, hub.tmux('display-message', '-p', '-t', pane, '#{pane_left} #{pane_top} #{pane_width} #{pane_height}').split())
                    capture = subprocess.run(['tmux', '-S', str(hub.SOCKET), 'capture-pane', '-e', '-p', '-t', pane], text=True, capture_output=True, check=True).stdout
                    render(draw, capture, 40 + x * 10, 58 + y * 24, w, h, background, fonts)
                draw.text((40, 1145), caption, font=fonts[1], fill='#ececec')
                draw.text((40, 1173), 'Scripted terminal demo · sample projects and responses', font=fonts[0], fill='#909090')
                path = frames / f'{len(scene_list):03d}.png'
                picture.save(path)
                scene_list.append((path, duration))
                if poster and args.poster:
                    args.poster.parent.mkdir(parents=True, exist_ok=True)
                    picture.save(args.poster)

            record('Projects and conversations, together.', 3)
            Demo.sidebar_click('1', 10, 6)
            Demo.wait_for(lambda: Demo.account_window('1')['kind'] == 'chat' and Demo.account_window('1')['pane'] and Demo.account_window('1')['sidebar'])
            Demo.chat = Demo.account_window('1')
            Demo.wait_for(lambda: 'demo-model' in Demo.capture() and 'Connecting' not in Demo.capture())
            Demo.click_text('Message Codex')
            prompt = 'Summarize this project'
            for chunk in ('Summarize ', 'this ', 'project'):
                os.write(Demo.fd, chunk.encode())
                Demo.wait_for(lambda: chunk.strip() in Demo.capture())
                record('Start a chat in your project.', .35)
            Demo.click_text('↑')
            Demo.wait_for(lambda: 'Project overview' in Demo.capture() and 'Read the docs' in Demo.capture())
            record('Markdown, tables and highlighted code — in the terminal.', 4, poster=True)
            Demo.click_text('Thinking')
            Demo.wait_for(lambda: 'Checking the project structure' in Demo.capture())
            record('Inspect thinking and tool output when you need it.', 2.6)
            Demo.click_text('Thinking')
            Demo.click_text('python -m pytest')
            Demo.wait_for(lambda: '3 tests passed' in Demo.capture())
            record('Tool details stay available after the turn ends.', 2.6)
            Demo.click_text('python -m pytest')
            (Demo.root / '1/control.json').write_text(json.dumps({'action': 'complete'}))
            Demo.wait_for(lambda: 'Completed' in Demo.capture())
            Demo.click_text('demo-model')
            Demo.wait_for(lambda: 'Choose model' in Demo.capture())
            record('Choose the model and reasoning for your next message.', 2.6)
            Demo.click_text('Demo lite')
            Demo.click_text('◇ Ask approval')
            Demo.wait_for(lambda: 'Approve for me' in Demo.capture())
            record('Set how actions are approved.', 2.6)
            Demo.click_text('Approve for me')
            Demo.click_text('Message Codex')
            os.write(Demo.fd, b'/')
            Demo.wait_for(lambda: '/compact' in Demo.capture())
            record('Slash commands are discoverable as you type.', 2.6)
            Demo.click_text('/model')
            Demo.click_text('Demo lite')
            # A generated sample graphic, not a screen capture or user image.
            sample = Image.new('RGB', (160, 100), '#16304b')
            artwork = ImageDraw.Draw(sample)
            artwork.rounded_rectangle((18, 17, 142, 83), radius=12, fill='#395d83')
            artwork.ellipse((59, 29, 101, 71), fill='#b8d9ef')
            sample.save(website / 'sample.png')
            Demo.click_text('+')
            Demo.click_text('sample.png')
            Demo.click_text('▧ 1')
            Demo.click_text('sample.png')
            Demo.click_text('Preview')
            Demo.wait_for(lambda: 'terminal thumbnail' in Demo.capture())
            record('Preview images without leaving the conversation.', 2.6)
            Demo.click_text('Back')
            Demo.click_text('▧ 1')
            Demo.click_text('sample.png')
            Demo.click_text('Remove attachment')
            # Exercise the actual scrolling UI on a synthetic longer reply.
            (Demo.root / '1/reply.md').write_text('\n\n'.join(f'### Section {n}\n\nA concise sample explanation for this part of the project.' for n in range(1, 13)))
            Demo.send_text('Explain the project in more detail')
            Demo.wait_for(lambda: 'Section 12' in Demo.capture())
            left, top = map(int, hub.tmux('display-message', '-p', '-t', Demo.chat['pane'], '#{pane_left} #{pane_top}').split())
            for _ in range(14):
                os.write(Demo.fd, f'\x1b[<64;{left+20};{top+15}M'.encode())
            Demo.wait_for(lambda: 'Section 12' not in Demo.capture())
            (Demo.root / '1/control.json').write_text(json.dumps({'action': 'append', 'text': '\n\nMore output arrives while you read.'}))
            Demo.wait_for(lambda: not (Demo.root / '1/control.json').exists())
            record('Scroll freely; streaming keeps your reading position steady.', 3.2)
            Demo.click_text('↓')
            Demo.wait_for(lambda: 'More output arrives' in Demo.capture())
            Demo.send_text('Add a short test plan')
            Demo.wait_for(lambda: '≡ 1' in Demo.capture() and 'Working on your action' not in Demo.capture())
            record('Queue a follow-up without interrupting the current turn.', 2.6)
            Demo.click_text('≡ 1')
            Demo.wait_for(lambda: 'Add a short test plan' in Demo.capture())
            record('Review and edit your queue.', 2.2)
            Demo.click_text('Back')
            Demo.click_text('■')
            Demo.wait_for(lambda: 'Queue paused' in Demo.capture())
            record('Persistent chats. Your projects. A native terminal workspace.', 3.2)
        finally:
            Demo.tearDownClass()
        playlist = frames / 'frames.txt'
        playlist.write_text(''.join(f"file '{path}'\nduration {duration}\n" for path, duration in scene_list) + f"file '{scene_list[-1][0]}'\n")
        subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y', '-f', 'concat', '-safe', '0', '-i', str(playlist), '-r', '24', '-c:v', 'libx264', '-crf', '20', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', '-metadata', 'comment=Scripted native TUI demo using synthetic projects and responses', str(args.output)], check=True)
        subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y', '-i', str(args.output), '-filter_complex', 'fps=8,scale=888:-1:flags=lanczos,split[a][b];[a]palettegen[p];[b][p]paletteuse=dither=bayer', '-loop', '0', str(args.gif)], check=True)
        print(json.dumps({'video': str(args.output), 'gif': str(args.gif), 'scenes': len(scene_list)}))


if __name__ == '__main__':
    main()
