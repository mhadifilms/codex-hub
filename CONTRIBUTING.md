# Contributing

## Development

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
```

Install tmux 3.2+ before running tests. Windows development uses WSL with the same commands. CI runs on macOS, Linux, and Windows/WSL.

The application uses Python curses for its interface, Rich for Markdown, tmux for persistent workspaces, and the Codex app-server's stdio protocol. Start with `bin/codex-hub-tui` and the focused modules under `lib/`.

Tests use disposable tmux servers and a deterministic backend. They exercise actual terminal mouse input, scrolling, queueing, permissions, restart recovery, conversation lifecycle, and platform integration. They do not need an account or send inference requests.

Keep changes focused. Add a regression test for a demonstrated bug, run the relevant checks, and include the result in your pull request. Run `git diff --check` before submitting.

For bug reports, include the OS, terminal, Hub version, relevant `codex-hub doctor` output, and reproduction steps. Remove credentials and private conversation content from attachments.

## Demo

`scripts/demo.py` drives the real terminal interface against sample projects and renders captured frames to GIF and MP4. It requires Pillow and ffmpeg.
