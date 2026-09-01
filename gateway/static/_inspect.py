import sys

path = r"C:\Users\lmq20\Documents\Kimi\Workspaces\ai伴侣\ai-companion\gateway\static\index.html"

with open(path, 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Find and print lines around the broken area
for i, line in enumerate(lines[660:690], start=661):
    print(f"{i}: {repr(line)}")
