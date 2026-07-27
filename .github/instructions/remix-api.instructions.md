---
applyTo: "**/remix_api.py,**/texture_processor.py"
---

# Remix REST client & texture pipeline

## remix_api.py (`RemixAPIClient`)
- **Every HTTP call goes through `make_request()`** — it owns retry logic and TLS policy. Never add a bare `requests.get/post`, and never bypass it for "just one" endpoint.
- TLS: `verify=False` only when the URL host is `localhost` / `127.0.0.1` / `[::1]` (the current check is a substring match — note `https://localhost.evil.com` also matches; tighten to real host parsing before this client ever talks to untrusted hosts). `verify=True` everywhere else.
- New endpoints: add a method that calls `make_request()`; keep request/response shaping in this module, not in `core.py`.
- Don't break the round-trip the rest of the plugin depends on: ingest → `update_textures_batch` → `save_layer`, and the material-hash relink used by force-push.

## texture_processor.py
- `texconv.exe` (bundled, DirectXTex / MIT) is shelled out with a hard `TEXCONV_TIMEOUT_SECONDS = 180`; Blender unwrap uses `BLENDER_TIMEOUT_SECONDS = 900`. Keep the timeouts and handle the timeout / non-zero-exit paths explicitly.
- Validate and normalize paths before shelling out; never build a shell command by concatenating untrusted input. Prefer argument lists over `shell=True`.
