# Changelog

## 0.1.3

Enter sends or queues messages; rapid double Enter steers the queued messages into the active turn (or starts them when idle). Display queued messages above the composer with per-message Steer, delete and edit controls. Preserve multiline paste and provide modified-Enter/newline controls. Open original images directly in the system viewer and remove lossy terminal thumbnails. Unconfirmed queued dispatch retains and pauses the queue instead of replaying it.

## 0.1.2

Fix chat closing and account-scoped project lists. New chats appear first; untouched empty chats stay out of history and repeated New chat reuses the empty pane. Show session and weekly usage remaining in the sidebar, with background refresh and last-known-value retention on failures. Stop replaces Send while an active composer is empty, and sits beside it while typing. Add visible Close and Exit controls. Mouse clicks place the caret inside multiline text; drag selects editable text or highlights/copies transcript text.

## 0.1.1

Fix existing-chat upgrades: visible running versions and update notice, safe same-pane reload with draft/history preservation, explicit Codex executable selection and backend diagnostics. Fast wheel input is batched before repainting, scroll sensitivity is available in Settings, and approvals use an anchored dropdown with an explicit Approve for me label. `/permissions` aliases `/approvals`. New panes reuse the launcher's Python environment.

## 0.1.0

Initial portable release of Codex Hub: a native tmux/curses workspace with projects, persistent chats, pins, rich Markdown, editable queues, model/reasoning controls, approvals, slash commands, context/compaction information, text selection and image previews.

Accounts and Codex homes are configured privately. The default setup uses one workspace; additional homes are optional and have no fixed count. Installation supports macOS/Linux and a configurable prefix.
