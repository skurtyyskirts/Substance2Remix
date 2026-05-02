# Substance2Remix — LLM Assistant Bootstrap

Substance Painter plugin bridging Adobe Substance 3D Painter with NVIDIA RTX Remix.

## Module Map (post-v0.5.0)

| File | Purpose |
|------|---------|
| `__init__.py` | Plugin registration entry; loads `core.py` via `_load_core_module()` |
| `core.py` | Central orchestration (~45 KB); `RemixConnectorPlugin` class |
| `remix_api.py` | REST client for RTX Remix Toolkit (~26 KB); `RemixAPIClient` class |
| `texture_processor.py` | DDS pipeline + texconv/Blender invocation (~11 KB) |
| `painter_controller.py` | Substance Painter API wrapper |
| `async_utils.py` | Qt worker thread + signal plumbing |
| `dependency_manager.py` | Runtime dependency loading |
| `diagnostics_dialog.py` | In-Painter diagnostics panel |
| `settings_dialog.py` | Tabbed settings UI |
| `settings_schema.py` | Settings key definitions and defaults |
| `qt_utils.py` | Qt helper utilities |
| `blender_auto_unwrap.py` | Blender background-mode UV unwrap script |
| `plugin_info.py` | Version/metadata constants |

## Key Entry Points

- `RemixConnectorPlugin.pull_from_remix()` — imports mesh + creates Painter project
- `RemixConnectorPlugin.push_to_remix()` — exports textures → ingest → update Remix material
- `RemixConnectorPlugin.force_push_to_remix()` — relinks to new material hash + push
- `RemixConnectorPlugin.import_textures_from_remix()` — pulls existing textures from linked material

## Network / TLS Policy

All HTTP calls go through `RemixAPIClient.make_request()`. TLS verification:
- **Disabled** (`verify=False`) for `localhost` / `127.0.0.1` / `[::1]` — Remix runs locally over HTTP
- **Enabled** (`verify=True`) for any non-loopback host

Do NOT add direct `requests.get/post` calls outside `make_request()`. All new endpoints
must use the method to preserve retry logic and TLS policy.

## texconv.exe Pipeline

`texture_processor.py` shells out to `texconv.exe` (bundled in repo root).
- Hard timeout: 180 s (`TEXCONV_TIMEOUT_SECONDS`)
- Blender unwrap timeout: 900 s (`BLENDER_TIMEOUT_SECONDS`)
- License: DirectXTex (MIT) — see `THIRD_PARTY_LICENSES.md`

## Install / Setup

No build step. Copy the plugin folder into Painter's `python/plugins/` directory.

## Running Tests

```bash
python -m pytest tests/
```

## Known PRs Pending Review

- **PR #1** (stale 2025-08): Metallic/Roughness vs Specular/Glossiness workflow toggle — rebase candidate
- **PR #2**: Production hardening — thread-safety, lifecycle, timeouts — needs final review
