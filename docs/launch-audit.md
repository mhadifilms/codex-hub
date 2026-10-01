# 0.1.0 launch audit

Reviewed the terminal UI, conversation lifecycle, queues and permissions, stdio transport, Markdown and configuration, and installation/distribution. The review combined source inspection, real tmux mouse tests against a deterministic backend, platform CI, a rendered UI/demo review, and TypeSafe judgments.

## Fixes

- Prevent database-excluded empty and archived chats from returning through the saved-record fallback.
- Close tabs through one tmux command, mark them closed before shutdown, and guard against the frontend reopening its record.
- Add right-click menus, archive/restore, and confirmed deletion of backend conversation history. Failed backend changes retain local metadata; project files are kept.
- Replace an unavailable curses window method, invalidate the physical screen cache during pane resizing, and forward mouse button releases to the application.
- Recover known unsent drafts whose backend thread was never persisted, preserving text and settings without sending a turn. Missing content-bearing conversations are reported instead of replaced.
- Close app-server pipes, including failed initialization paths.
- Add dependency setup, custom-prefix install/upgrade/uninstall checks, and Windows/WSL installation with literal Windows clipboard and link commands.
- Simplify ambiguous glyphs, retain familiar send/stop/close controls, and render context usage as a percentage.

## TypeSafe

Used the `typesafe-ai` workflow with `jev-latest` (returned model `jev-1.13.0`) for 35 independent Noul propositions across five source bundles. [Sanitized results](typesafe-audit.json) include source hashes, model identifiers, usage, and answers before and after the implementation pass. Authentication remained in the local Keychain; only public application source was supplied.

These are advisory probability judgments, not runtime test results or an overall pass score. Positive and negative propositions have different meanings. Examples from the final source pass: right-click discoverability 0.91, archive/restore 0.91, scrolling anchors 0.66, composer selection 0.95, installed model catalog 0.94, and native Markdown 0.92.

The model remained uncertain about the close race (negative proposition 0.71) and whole-conversation deletion (positive proposition 0.44). Independently inspected the shutdown guards and verified close/delete behavior, delete cancellation, backend-error retention, and restart exclusions through real mouse input. Its low macOS/Linux CI judgment and favorable Homebrew judgment did not establish either execution result; those require actual CI and installation checks. The whole-conversation deletion question was made explicit in the after pass, so its score is not a direct before/after comparison.

Oversized lifecycle and interaction requests were rejected by the service. Retried those groups with the complete UI source alone; all five groups completed. The final interaction bundle excludes test fixtures, so its scores are not a direct comparison with earlier source-and-test bundles. No credentials or private conversations are included in this report or the results.

## Limits

tmux 3.4 can suppress the first left press shortly after a right click. The Linux lifecycle test waits for that version's 300 ms click timer; it does not establish rapid button-change reliability. Use the regular chat controls, pause briefly, or upgrade tmux. See the [tmux 3.4 input implementation](https://github.com/tmux/tmux/blob/3.4/server-client.c#L589-L627).

Behavioral tests use a deterministic local backend rather than live inference. Protocol shapes were checked against Codex CLI 0.159.2. Windows support is through WSL, not a Win32 curses port. Terminal font rendering and modified-key reporting vary by emulator. Images open their original files in a system viewer. Passing tests and model judgments do not guarantee every terminal/backend combination.
