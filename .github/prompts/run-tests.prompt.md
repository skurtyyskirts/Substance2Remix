---
mode: agent
description: Run the Substance2Remix test suite and interpret failures.
---

Run the plugin's tests and report.

1. `python -m pytest tests/ -v`.
2. If imports fail on Qt / Painter symbols, that's a missing `QT_AVAILABLE` guard — point at the unguarded import; do not "fix" it by installing a GUI.
3. Summarize: pass/fail counts, the first real failure with `file:line` and root cause, and the minimal fix. Don't widen timeouts or add retries to make a flaky test pass — find why it's flaky.
