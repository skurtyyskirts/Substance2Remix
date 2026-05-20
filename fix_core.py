with open('core.py', 'r') as f:
    content = f.read()

content = content.replace(
    '{"p_channel": "ao", "pbr_type": "ao"}',
    '{"p_channel": "ambientOcclusion", "pbr_type": "ao"}'
)

with open('core.py', 'w') as f:
    f.write(content)
