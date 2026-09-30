# Changelog

## 0.1.1

Fix existing-chat upgrades: visible running versions and update notice, safe same-pane reload with draft/history preservation, explicit Codex executable selection and backend diagnostics. Fast wheel input is batched before repainting, scroll sensitivity is available in Settings, and approvals use an anchored dropdown with an explicit Approve for me label. `/permissions` aliases `/approvals`. New panes reuse the launcher's Python environment.

## 0.1.0

Initial portable release of Codex Hub: a native tmux/curses workspace with projects, persistent chats, pins, rich Markdown, editable queues, model/reasoning controls, approvals, slash commands, context/compaction information, text selection and image previews.

Accounts and Codex homes are configured privately. The default setup uses one workspace; additional homes are optional and have no fixed count. Installation supports macOS/Linux and a configurable prefix.
