with open('core.py', 'r') as f:
    content = f.read()

# 1. Incorrect AO Export Map Name: `{"p_channel": "ao", "pbr_type": "ao"}` -> `{"p_channel": "ambientOcclusion", "pbr_type": "ao"}`
# I need to see where "ao" is present in `maps_to_create`.
# Oh, it's not even present in the current maps_to_create? I need to check what Cursor is talking about.
