import re, os

src = open('ds-raw.md','rb').read()
text = src.decode('utf-8')
lines = text.split('\n')

blocks = []
i = 0
while i < len(lines):
    if lines[i].strip() == '```python':
        start = i + 1
        j = start
        while j < len(lines) and lines[j].strip() != '```':
            j += 1
        blocks.append(lines[start:j])
        i = j + 1
    else:
        i += 1

print("num blocks:", len(blocks))
for b in blocks:
    print("  block lines:", len(b), "first:", b[0][:60])

os.makedirs('extracted', exist_ok=True)
# order: service_policy.py then tests/test_service_policy.py
names = ['extracted/service_policy.py', 'extracted/test_service_policy.py']
for name, b in zip(names, blocks):
    content = '\n'.join(b) + '\n'
    with open(name, 'w', encoding='utf-8') as f:
        f.write(content)
    print("wrote", name, os.path.getsize(name))
