---
mode: agent
description: Triage a GitHub issue for Substance2Remix — classify, label, hypothesize, ask for the right logs.
---

Triage the issue I give you (title + body, or a number if GitHub MCP is available): ${input:issue:Issue number, or title + body}

Produce:
1. **Labels** (≤3) from the repo's label set; prefer specificity (don't apply both `bug` and `question`).
2. **Exactly one** of: a root-cause hypothesis (only if diagnosable), a specific clarifying question (name the missing field — Painter version? Remix Toolkit version? OS?), or a concrete next step.
3. For runtime failures, ask for the `Documents/Substance2Remix` logs plus the Painter + Remix Toolkit versions before deep analysis. For "X broke after a Painter update", consider delegating to **painter-api-compat-monitor**; for upstream Remix REST changes, **research-scanner**.

Keep the comment 3–5 sentences. If GitHub MCP is available you may apply labels and post; otherwise output them for me to paste.
