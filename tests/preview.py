"""Render actual disposable tmux pane captures for visual review (requires Pillow)."""
import re
import sqlite3
import subprocess
import sys
import time
import unicodedata
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
from test_hub import HubIntegration, hub


def color(index):
    if index < 16:
        return ['#000000', '#800000', '#008000', '#808000', '#000080', '#800080', '#008080', '#c0c0c0',
                '#808080', '#ff0000', '#00ff00', '#ffff00', '#0000ff', '#ff00ff', '#00ffff', '#ffffff'][index]
    if index >= 232:
        value = 8 + (index - 232) * 10
        return (value, value, value)
    index -= 16
    levels = [0, 95, 135, 175, 215, 255]
    return tuple(levels[n] for n in (index // 36, index // 6 % 6, index % 6))


def render(draw, capture, left, top, width, height, background, font):
    cell, line = 10, 24
    draw.rectangle((left, top, left + width * cell, top + height * line), fill=color(background))
    fg, bg, bold, underline = 253, background, False, False
    for row, text in enumerate(capture.splitlines()):
        column = 0
        for token in re.split(r'(\x1b\[[0-9;]*m)', text):
            if token.startswith('\x1b['):
                codes = [int(n or 0) for n in token[2:-1].split(';')]
                while codes:
                    code = codes.pop(0)
                    if code == 0:
                        fg, bg, bold, underline = 253, background, False, False
                    elif code == 1:
                        bold = True
                    elif code == 22:
                        bold = False
                    elif code in (4, 24):
                        underline = code == 4
                    elif 30 <= code <= 37:
                        fg = code - 30
                    elif 90 <= code <= 97:
                        fg = code - 90 + 8
                    elif code in (38, 48) and len(codes) >= 2 and codes[0] == 5:
                        codes.pop(0)
                        if code == 38:
                            fg = codes.pop(0)
                        else:
                            bg = codes.pop(0)
                    elif code == 39:
                        fg = 253
                    elif code == 49:
                        bg = background
                continue
            for char in token:
                cells = 2 if unicodedata.east_asian_width(char) in ('W', 'F') else 1
                x, y = left + column * cell, top + row * line
                draw.rectangle((x, y, x + cells * cell - 1, y + line - 1), fill=color(bg))
                glyph_font = font[1 if bold else 0]
                if len(font) > 2 and char in '☰⧉ⓘ▧':
                    glyph_font = font[2]
                if len(font) > 3 and char == 'ⓘ':
                    glyph_font = font[3]
                draw.text((x, y + 2), char, font=glyph_font, fill=color(fg))
                if underline:
                    draw.line((x, y + 20, x + cells * cell - 1, y + 20), fill=color(fg))
                column += cells


def main(output):
    test = HubIntegration
    test.setUpClass()
    try:
        website, project = test.root / 'Website', test.root / 'Codex Hub'
        website.mkdir()
        project.mkdir()
        hub.remember('1', project)
        hub.remember('1', website)
        with sqlite3.connect(test.root / '1/state_5.sqlite') as db:
            db.execute('DELETE FROM threads')
            for ident, title, path, age in [('1', 'Refine the chat workspace', project, 5400),
                                           ('2', 'Polish onboarding flow', website, 7200),
                                           ('3', 'Improve billing settings', website, 86400)]:
                db.execute('INSERT INTO threads VALUES(?,?,?,0,1,?)', (ident, title, str(path), int(time.time()) - age))
        test.wait_for(lambda: 'Polish onboarding' in test.sidebar_text('1'))
        home = test.account_window('1')
        test.wait_for(lambda: 'Website' in hub.tmux('capture-pane', '-p', '-t', home['pane']))
        picture = Image.new('RGB', (1400, 1004), color(234))
        draw = ImageDraw.Draw(picture)
        fonts = [ImageFont.truetype('/System/Library/Fonts/Menlo.ttc', 16, index=i) for i in (0, 1)]
        font = fonts[0]
        draw.text((20, 2), 'Codex', font=font, fill=color(245))
        draw.text((1090, 2), 'Workspace · Home', font=font, fill=color(245))
        for pane, background in ((home['sidebar'], 233), (home['pane'], 234)):
            x, y, w, h = map(int, hub.tmux('display-message', '-p', '-t', pane,
                                        '#{pane_left} #{pane_top} #{pane_width} #{pane_height}').split())
            capture = subprocess.run(['tmux', '-S', str(hub.SOCKET), 'capture-pane', '-e', '-p', '-t', pane],
                                     text=True, capture_output=True, check=True).stdout
            render(draw, capture, x * 10, (y + 1) * 24, w, h, background, fonts)
        draw.text((20, 972), 'Rendered terminal capture · fixture conversations', font=font, fill=color(245))
        Path(output).parent.mkdir(parents=True, exist_ok=True)
        picture.save(output)
    finally:
        test.tearDownClass()


if __name__ == '__main__':
    main(sys.argv[1])
