---
mode: agent
description: Review a Substance2Remix change for correctness, security, and the project's invariants.
---

Review the change I point you at (a diff, a branch, or PR #${input:pr:PR number — or paste a diff}).

Focus, in order:
1. **Correctness** — wrong logic, unhandled `None`, races in `async_utils.py` Qt threads.
2. **Security** — bare `requests` calls bypassing `make_request()`, TLS `verify` weakened for non-local hosts, command injection in the texconv/Blender shell-out, leaked secrets, unsafe deserialization.
3. **Invariants** — Remix round-trip intact, `QT_AVAILABLE` guards present, texconv/Blender timeouts kept.
4. Tests present for behavior changes; `CHANGELOG.md` updated.

Cite findings as `path:line`, grouped **HIGH / MEDIUM / LOW**, one sentence + a fix each. Note the two pending PRs in `CLAUDE.md` if this overlaps them. If the diff is clean, say so in one line.
