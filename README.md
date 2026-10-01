# Codex Hub

A native terminal workspace for Codex. Organize projects and chats, read rich Markdown, keep work running in tmux, and pick up where you left off.

![Codex Hub terminal demo](docs/demo.gif)

*Scripted terminal demonstration with sample projects and responses. No personal data or live credentials.*

## Install

Requires macOS or Linux, **Python 3.10+**, **tmux 3.2+**, and the [Codex CLI](https://developers.openai.com/codex/cli/). A terminal with mouse reporting and 256 colors works best.

```sh
git clone https://github.com/mhadifilms/codex-hub.git
cd codex-hub
./install.sh
codex-hub
```

The installer uses `~/.local/bin`, creates a private Python environment for Rich and Pillow, and reports if that bin directory needs adding to PATH. `./install.sh --prefix /your/path` changes the install location. `--no-deps` uses your existing Python installation when Rich and Pillow are already installed.

The default workspace uses your existing `~/.codex` home. If it is not signed in, run `codex login` with the normal browser flow. Existing isolated hub homes are discovered during an upgrade; credentials and chat history stay in place.

## The workspace

- **Projects and chats:** click Add project to browse or create folders. Each account has its own project list and searchable chat sidebar. New chats appear first; untouched empty chats stay out of saved history. Repeated New chat reuses an empty pane. Close a tab with × or its ··· menu; saved content is retained.
- **Native Markdown:** headings, bold/italic text, lists, quotes, tables, inline code and highlighted code blocks render directly in the terminal. Links are clickable.
- **Composer:** type multiline messages, attach images, choose a model and reasoning effort, and press Enter or click ↑ to send. Double Enter sends the queue into the active turn, or starts it when idle. Use ↵ or Alt+Enter for a newline; Shift+Enter also works when the terminal reports a distinct key sequence. Multiline bracketed paste stays in the draft until explicitly sent. Click within text to place the caret, or drag to select and replace text. While a turn runs, ■ replaces Send when the composer is empty; while typing it sits to the left of ↑. ↑ queues the message; ↳ steers the active turn.
- **Queues:** messages stack above the composer with per-message ↳ Steer, ⌫ delete and ··· edit/options controls. Double Enter dispatches the queued messages together; click a row’s Steer to dispatch only that message. Click ≡ to review all pending messages. Interrupted, failed, or recovered queues pause for review before resuming.
- **Permissions:** the ◇ dropdown selects explicit approvals, automatic risk review, or full access for the next turn. Full access grants unrestricted file/network access without approval prompts.
- **Context:** hover ◔ to see reported context usage and compaction status. Click it, or use `/compact`, to compact an idle chat.
- **Activity:** thinking and tool calls stay visible and expandable after a turn finishes. User messages have distinct, bright bubbles.
- **Selection:** drag across transcript text to highlight and copy it. Drag within the composer selects editable text; ⧉ copies that selection when present. ▣ enters tmux text selection mode. Drag to select/copy; ⧉ copies the latest response. Clipboard integration uses the terminal, `pbcopy`, `wl-copy`, or `xclip` where available. Shift-drag may also select directly in your terminal emulator.
- **Images:** + browses local image files. Image preview and linked images open the original file directly in the system viewer, at full resolution. No terminal thumbnail conversion is performed.
- **Scrolling:** wheel/trackpad movement, a draggable scrollbar, Page Up/Down and a jump-to-latest control. Reading position stays anchored while output streams or the terminal resizes; reaching the bottom resumes following.
- **Usage:** the bottom-left sidebar shows session and weekly percentages remaining. Read-only snapshots refresh in the background about once a minute while the account is visible; failures retain the last verified values and show a warning marker. Hover for verification time.
- **Exit:** click ⏻ Exit in the sidebar or ⏻ in the chat header. The UI detaches while chats keep running; reopen `codex-hub` to return.
- **Persistence:** reopening the hub restores open enhanced chats, their drafts, selected models, and paused queues. Closing a chat marks its tab closed while retaining saved history.

### After upgrading

Existing chat processes keep running their original frontend until reconnected. The sidebar shows **↻ Update this chat** for an older frontend. Open its **···** menu and choose **Reload chat**, then confirm; stop active work first. Drafts, history and paused queues are retained. `codex-hub reload ACCOUNT` reconnects idle enhanced chats. `--force` confirms restarting a legacy frontend that cannot report its activity; busy current frontends are still refused. The running version appears above the conversation and in the sidebar.

Use `codex-hub doctor` or `/status` to see the exact backend executable and version. If your terminal's PATH selects an older CLI, set `codexBinary` to the desired executable in the private JSON config, then reload idle chats. `CODEX_HUB_CODEX` is an optional environment override. Model choices come from that backend's catalog; catalog visibility alone does not verify inference access.

Icons show explanatory labels on hover. The interface works in an 80-column terminal; ☰ collapses the sidebar to make more room.

Slash commands include `/model`, `/approvals` (also `/permissions`), `/compact`, `/status`, `/new`, `/resume`, `/stop`, `/queue`, `/pin`, and `/help`. Suggestions appear while typing `/`. Press Enter to run a slash command; Enter in ordinary message text sends or queues it. CLI-specific slash commands fail explicitly and can be used through **Open in Codex CLI** in chat details.

## Configuration

Click **Settings** in the sidebar to add an account, edit its display label/description, choose a default, or sign in. There is no fixed account count. Additional accounts are optional; each can use an existing Codex home or a new isolated home.

```sh
codex-hub config                         # print the private config path
codex-hub accounts add work --label Work
codex-hub accounts login work
codex-hub accounts edit work --default
codex-hub accounts list
```

The config is JSON, outside the repository:

```json
{
  "schemaVersion": 1,
  "defaultAccount": "default",
  "scrollLines": 1,
  "accounts": {
    "default": {
      "label": "Default",
      "description": "Local workspace",
      "home": "~/.codex"
    }
  }
}
```

Use any command-safe account ID and display label. `scrollLines` controls wheel sensitivity (1–20 lines per event); Settings cycles through precise, normal and fast scrolling. Rapid wheel events are batched before repainting. `--home /path/to/codex-home` reuses an existing home; otherwise Add creates a private isolated home. `accounts remove ID` removes the config entry only and refuses while that workspace's tmux session exists. Files, credentials and history are retained. Stop the relevant session before changing its home path manually.

Fresh installs store settings under `$XDG_CONFIG_HOME/codex-hub` or `~/.config/codex-hub`. Upgrades reuse `~/.codex-subs` when present. Set `CODEX_HUB_ROOT` to choose another state/config directory. Private settings and credentials never belong in the repository.

Optional shell entry points:

```sh
codex-hub new default ~/projects/website 'Website work'
codex-hub list
codex-hub cli default ~/projects/website
codex-hub usage all
codex-hub --version
```

`codex-sub` and `codex-hub-usage` remain as compatibility aliases. Project files are shared filesystem data; separate Git worktrees are useful when concurrent chats edit the same repository.

## Boundaries

Codex Hub connects to the installed Codex app-server through stdin/stdout. There is no browser UI or localhost server. Available models and protocol behavior follow your installed CLI and account. Version 0.1.0 was checked against Codex CLI 0.146.0; behavioral tests use a deterministic local backend rather than live inference.

The terminal owns fonts and line spacing. Images open in the system viewer using the original file. The TUI does not convert images into colored terminal cells. Desktop voice, embedded browser/editor panels, clipboard-image paste, and desktop-only plugins are not supported. Client interactions outside supported chat, approval and question requests fail explicitly with a stock CLI fallback. Pins and display names are local to the hub.

## Development

```sh
python3 -m pip install -r requirements.txt
python3 -m unittest discover -s tests -v
```

Tests create disposable tmux servers and fake account homes. They check actual terminal mouse input, native Markdown, queues, permissions, configurable homes, restart recovery, and the compact layout without production credentials.

The [demo generator](scripts/demo.py) drives the real TUI against sample data and renders its captured terminal frames into an MP4 and GIF. It needs Pillow and ffmpeg. No real desktop or account contents are captured.

MIT licensed. See [CHANGELOG](CHANGELOG.md).
