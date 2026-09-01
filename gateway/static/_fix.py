import sys

path = r"C:\Users\lmq20\Documents\Kimi\Workspaces\ai伴侣\ai-companion\gateway\static\index.html"

with open(path, 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Fix 1: Remove broken lines 672-673 (0-based index 671, 672)
# These are garbage repeated from line 671
del lines[671]  # was line 672
del lines[671]  # was line 673, now shifted to 671

# Fix 2: Remove duplicate CSS block at lines 38-50 (0-based 37-49)
# After fix 1, line numbers are -2, so lines 38-50 are now at 36-48
# The duplicate block starts at 0-based index 37 (was 38)
# Let's find it by searching for the duplicate pattern
start_dup = None
for i, line in enumerate(lines):
    if i > 30 and '--primary: #2563eb;' in line:
        start_dup = i
        break

if start_dup is not None:
    # Find the end of the duplicate block - it goes until just before the closing } of :root
    # The original :root ends around line 36, then the duplicate starts
    # We need to remove from start_dup until the line that closes this duplicate :root
    end_dup = start_dup
    for j in range(start_dup, min(start_dup + 20, len(lines))):
        if lines[j].strip() == '}':
            end_dup = j
            break
    # Remove the duplicate block (from start_dup to end_dup inclusive)
    del lines[start_dup:end_dup+1]

with open(path, 'w', encoding='utf-8') as f:
    f.writelines(lines)

print("Fixed!")
print(f"Total lines: {len(lines)}")

# Verify JS syntax by writing a temp check file
js_check = r"C:\Users\lmq20\Documents\Kimi\Workspaces\ai伴侣\ai-companion\gateway\static\_check_js.js"
with open(path, 'r', encoding='utf-8') as f:
    html = f.read()

# Extract script content
import re
scripts = re.findall(r'<script>(.*?)</script>', html, re.DOTALL)
with open(js_check, 'w', encoding='utf-8') as f:
    f.write('\n'.join(scripts))

print("JS extraction done.")
