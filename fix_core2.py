with open('core.py', 'r') as f:
    content = f.read()

content = content.replace(
    '"ao": "AO", "opacity": "OPACITY",',
    '"ao": "AO", "opacity": "OPACITY", "specular": "SPECULAR", "glossiness": "GLOSSINESS",'
)

with open('core.py', 'w') as f:
    f.write(content)
