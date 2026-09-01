path = r"C:\Users\lmq20\Documents\Kimi\Workspaces\ai伴侣\ai-companion\gateway\static\index.html"

with open(path, 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Delete lines 38-65 (0-based index 37 to 64 inclusive)
# These are the leftover duplicate :root variables
del lines[37:65]

with open(path, 'w', encoding='utf-8') as f:
    f.writelines(lines)

print(f"Deleted duplicate CSS block. Total lines: {len(lines)}")

# Verify the area looks correct now
for i in range(30, 42):
    print(f"{i+1}: {lines[i].rstrip()}")
