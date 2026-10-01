# Codex Hub

[![Tests](https://github.com/mhadifilms/codex-hub/actions/workflows/test.yml/badge.svg)](https://github.com/mhadifilms/codex-hub/actions/workflows/test.yml)
[![Release](https://img.shields.io/github/v/release/mhadifilms/codex-hub)](https://github.com/mhadifilms/codex-hub/releases/latest)
[![MIT License](https://img.shields.io/github/license/mhadifilms/codex-hub)](LICENSE)
![Platforms](https://img.shields.io/badge/platforms-macOS%20%7C%20Linux%20%7C%20Windows%20%28WSL%29-555)

**A terminal workspace that makes Codex feel at home.**

Organize projects and chats in a clickable sidebar, read native Markdown, steer running work, and return to your conversations after a restart. Powered by the official [Codex CLI](https://developers.openai.com/codex/cli/) and tmux.

![Codex Hub](docs/demo.gif)

## Install

Requires Python **3.10+**, tmux **3.2+**, Codex CLI **0.159+**, and a terminal with mouse reporting and 256 colors.

### Homebrew · macOS and Linux

```sh
brew install mhadifilms/codex-hub/codex-hub
# If Codex CLI is not installed:
brew install --cask codex
codex login
codex-hub
```

### From source · macOS and Linux

```sh
git clone https://github.com/mhadifilms/codex-hub.git
cd codex-hub
./install.sh --bootstrap
codex login
~/.local/bin/codex-hub
```

`--bootstrap` installs missing dependencies using Homebrew on macOS or apt/npm on Debian and Ubuntu. On other Linux distributions, install the requirements with your package manager and run `./install.sh`.

The installer creates a dedicated Python environment. Add `~/.local/bin` to your shell's PATH to use `codex-hub` directly. Use `--prefix /your/path` for a different install location, or `--no-deps` when the selected Python already has Rich and Pillow.

### Windows · Windows Terminal + WSL

Windows support runs inside WSL; tmux and curses require a Linux terminal environment.

1. In an administrator PowerShell, run `wsl --install`. Restart if requested, then open Ubuntu once to finish setup.
2. Clone or download this repository, then run PowerShell in its directory:

   ```powershell
   powershell -ExecutionPolicy Bypass -File .\install.ps1
   ```

3. Open **Ubuntu** in Windows Terminal:

   ```sh
   codex login
   ~/.local/bin/codex-hub
   ```

Use `-Distribution NAME` if your WSL distribution has another name. The installer supports Ubuntu/Debian dependency setup; `-NoBootstrap` uses existing dependencies. Clipboard copy and links use Windows applications when WSL interoperability is available. Store active projects in the Linux filesystem for better performance.

## The workspace

| Feature | How it works |
| --- | --- |
| Projects and chats | Click **Add project** to browse or create folders. Search chats, pin favorites, and keep recent work at the top. |
| Chat management | Right-click a chat or use **···** to rename, pin, close, archive, or delete it. **Archived chats** lets you restore conversations. Delete requires confirmation. |
| Drafts | Untouched empty chats stay out of history. Nonempty drafts appear as **Draft** and survive restarts while their tab is open. |
| Messages and queues | **Enter** sends, or queues while Codex is working. **Double Enter** dispatches the queue into the active turn. Each queued message has Steer, edit, and delete controls. |
| Multiline input | **Alt+Enter** or **↵** inserts a newline. Bracketed multiline paste stays in the draft until sent. Shift+Enter works when your terminal reports it distinctly. |
| Markdown | Styled paragraphs, headings, lists, tables, quotes, links, and highlighted code render directly in the terminal. |
| Scrolling | Wheel/trackpad input, a draggable scrollbar, Page Up/Down, and jump to latest. Reading position stays anchored during streaming and resizing. |
| Activity | Thinking and tool calls remain expandable after a turn finishes. User messages have distinct bubbles. |
| Models and permissions | Choose models and reasoning effort from the installed backend's catalog. The **◇** dropdown offers Ask approval, Approve for me, and Full access. Full access allows unrestricted file/network actions without approval prompts. |
| Context and usage | Hover **◔** for context usage and compaction status. The sidebar shows verified session and weekly percentages remaining. |
| Selection | Click to position the composer caret; drag to select text. **⧉** copies selection or the latest response. **▣** opens tmux text selection mode. |
| Images and links | **+** attaches local images. Preview opens the original image in the system viewer at full resolution. Click links to open them. |
| Persistence | Reopen the hub to restore open chats, drafts, model choices, and paused queues. Close stops a tab and keeps history; archive hides history until restored. |
| Exit | Click **⏻ Exit** to detach. Chats keep running in tmux until stopped or closed. |

Icons show labels on hover. **☰** collapses the sidebar for more room; the layout supports an 80-column terminal.

### Slash commands

`/model`, `/approvals` (`/permissions`), `/compact`, `/status`, `/new`, `/resume`, `/stop`, `/queue`, `/pin`, and `/help` run locally when you press Enter. Suggestions appear while typing `/`. Unsupported CLI commands report an explicit error; chat details offer **Open in Codex CLI** for CLI-specific workflows.

### Configuration

The default workspace uses your existing `~/.codex` home. Click **Settings** to adjust scrolling, rename a workspace, choose a default, or add another Codex home. Additional homes are optional and each has its own chat and project lists.

```sh
codex-hub config                         # config file location
codex-hub accounts add work --label Work
codex-hub accounts login work
codex-hub accounts edit work --default
codex-hub doctor                         # backend path, version, and diagnostics
```

Settings live under `$XDG_CONFIG_HOME/codex-hub` or `~/.config/codex-hub`. Existing installations reuse `~/.codex-subs`. Set `CODEX_HUB_ROOT` to choose another directory. `scrollLines` sets wheel sensitivity from 1–20 lines per event; Settings includes precise, normal, and fast presets.

Use `--home /path/to/codex-home` with `accounts add` to reuse another existing Codex home. Otherwise it creates an isolated home. Removing an account removes its configuration entry and retains its files. Projects are ordinary filesystem folders; separate Git worktrees help when simultaneous chats edit the same repository.

### Updates and uninstall

```sh
brew upgrade mhadifilms/codex-hub/codex-hub
brew uninstall codex-hub
```

For source installs, `git pull` and rerun the installer. `./uninstall.sh` removes the installed Hub launchers and libraries while retaining configuration, chats, and Codex CLI. Use the same `--prefix` as installation.

Existing chats keep their running frontend until reloaded. Stop active work, then use **··· → Reload chat** or `codex-hub reload ACCOUNT`. Drafts and saved history are retained; recovered queues pause for review. The sidebar marks older frontends with **Update this chat**.

## Terminal compatibility

The terminal controls fonts and line spacing. Clipboard support uses `pbcopy`, Windows PowerShell under WSL, `wl-copy`, or `xclip`; tmux provides a copy buffer fallback. Image preview opens an external viewer. Desktop voice, embedded browser/editor panels, clipboard-image paste, and desktop-only plugins are not supported.

Codex Hub talks to the installed app-server through stdin/stdout. Models and protocol capabilities follow that CLI and the signed-in account. Run `codex-hub doctor` to diagnose an unexpected catalog or connection failure. Set `codexBinary` in config, or `CODEX_HUB_CODEX`, to select another executable.

If a chat stays on **Connecting**, check `doctor` and `codex login status`, then use Retry. Hub recovers an unsent draft when the backend no longer has its empty thread; missing conversations with sent messages are reported instead of replaced.

## Contributing

See [CONTRIBUTING](CONTRIBUTING.md), [CHANGELOG](CHANGELOG.md), and [security reporting](SECURITY.md). Issues and pull requests are welcome.

Independent open-source client for OpenAI Codex. [MIT licensed](LICENSE).
