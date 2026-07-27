---
applyTo: "**/*.py"
---

# Python — Substance2Remix

Plugin code for Substance 3D Painter (Python 3, PySide/Qt). No build step; tests run headless on Linux CI.

- Keep functions small and single-purpose; type hints over comments about types; Google-style docstrings (`Args:` / `Returns:` / `Raises:`) on public methods. Prefer renaming over narrating.
- **Guard every Substance Painter / Qt import and call behind the existing `QT_AVAILABLE` (and Painter-availability) checks** — headless CI must still import the module.
- No catch-all `except Exception: pass`. Handle expected errors; let unexpected ones raise. Don't widen timeouts or add retries to mask a real failure.
- Run `python -m pytest tests/` for anything you touch before claiming completion; add or adjust tests with behavior changes.
- `async_utils.py` owns Qt worker threads + signals — do background work there and never block Painter's UI thread. Keep signal signatures stable (`core.py` consumes them).
- Never commit secrets / API keys or unintended `_vendor/` binaries.
