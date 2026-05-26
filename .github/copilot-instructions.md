# Copilot Instructions — Substance2Remix

A **Substance Painter plugin** (Python) that imports/exports textures between Substance Painter and the RTX Remix Toolkit.

## Orientation
- Read `CLAUDE.md` first.
- Core modules: `core.py`, `remix_api.py` (REST client for the Remix Toolkit), `painter_controller.py`, `texture_processor.py`, `async_utils.py`. UI uses PySide/Qt (`*_dialog.py`, `qt_utils.py`).
- Tests live in `tests/` — run them before claiming work complete.

## Conventions
- Match the style of the file you are editing; keep functions small and single-purpose.
- Don't break the Remix round-trip pipeline (`ingest_texture` → `update_textures_batch` → `save_layer`) or the request/retry logic in `remix_api.py`.
- Guard Qt usage behind the existing `QT_AVAILABLE` checks so headless tests keep working.
- Add or update tests when changing behavior; update `CHANGELOG.md` for notable changes.
- Never commit secrets, API keys, or vendored binaries you didn't intend to.
