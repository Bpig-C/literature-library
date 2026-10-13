# Evidence and links

## Keep evidence types separate

Use the project’s own names and records, while preserving these distinctions when they matter:

- A user decision is not the same as an assistant proposal or a draft.
- Static code describes a checked revision; it does not prove a running service or deployed build.
- A dated runtime snapshot is not a live status unless checked again.
- Candidate branches, worktrees, production data, and local development state are separate evidence scopes.
- Software validation does not establish scientific correctness, user understanding, or human adoption.
- Historical reports remain evidence of what was known at their date; add a later account rather than rewriting them.

When evidence conflicts, follow the most direct available source, record its date and scope, and preserve unresolved uncertainty. Do not infer a new requirement from an exception, failing test, or implementation shortcut.

## Check links semantically

For each important cross-document reference:

1. Confirm that the file or versioned object exists.
2. Confirm that the anchor or named section exists in that object.
3. Read enough of the target to verify it still contains the cited subject and supports the surrounding claim.
4. If the target moved, replace it with a stable ID, real heading anchor, or immutable commit-and-path reference. Include a reproducible read command for historical Git objects.
5. Keep current execution instructions separate from historical plans and decisions.

Line numbers can help a reviewer find text, but should not be the only locator. Follow the project’s conventions for local links and cross-project paths.
