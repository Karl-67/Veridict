"""
Rebuild a clean linear history from chain 2 of the doubled 45ead38 state.
Deduplicates by tree hash (oldest-first, keep first occurrence = original commits).
Uses git commit-tree to preserve author/date metadata exactly.
"""
import subprocess, os, re, sys

CHAIN2_TIP = '8aea3d030fad6d3a804c0b028703b1343af137f5'

def run(cmd, env=None):
    r = subprocess.run(cmd, capture_output=True, text=True, env=env)
    if r.returncode != 0:
        print(f"ERROR: {' '.join(cmd)}\n{r.stderr}", file=sys.stderr)
        sys.exit(1)
    return r.stdout.strip()

def parse_ident(s):
    m = re.match(r'^(.*?) <([^>]*)> (\d+) ([+-]\d{4})$', s)
    if m:
        return m.group(1), m.group(2), m.group(3), m.group(4)
    return 'Unknown', 'unknown@unknown.com', '0', '+0000'

# Step 1: collect all commits from chain 2, newest-first
print(f"Collecting commits from chain 2 ({CHAIN2_TIP[:8]})...")
raw = run(['git', 'log', '--format=%H %T', CHAIN2_TIP])
all_commits = [(l.split()[0], l.split()[1]) for l in raw.split('\n')]
print(f"Total: {len(all_commits)} commits")

# Step 2: deduplicate by tree hash — go oldest-first, keep first occurrence (original)
seen_trees = set()
keep = []
for h, t in reversed(all_commits):
    if t not in seen_trees:
        seen_trees.add(t)
        keep.append(h)
print(f"After dedup: {len(keep)} commits to rebuild")

# Step 3: rebuild using git commit-tree
new_tip = None
for i, old_h in enumerate(keep):
    raw_obj = subprocess.run(
        ['git', 'cat-file', 'commit', old_h],
        capture_output=True, text=True
    ).stdout

    lines = raw_obj.split('\n')
    tree = author = committer = None
    msg_start = 0
    for j, line in enumerate(lines):
        if line.startswith('tree '):
            tree = line.split()[1]
        elif line.startswith('author '):
            author = line[7:]
        elif line.startswith('committer '):
            committer = line[10:]
        elif line == '':
            msg_start = j + 1
            break

    message = '\n'.join(lines[msg_start:]).rstrip('\n')
    an, ae, at, atz = parse_ident(author)
    cn, ce, ct, ctz = parse_ident(committer)

    env = os.environ.copy()
    env['GIT_AUTHOR_NAME']     = an
    env['GIT_AUTHOR_EMAIL']    = ae
    env['GIT_AUTHOR_DATE']     = f"{at} {atz}"
    env['GIT_COMMITTER_NAME']  = cn
    env['GIT_COMMITTER_EMAIL'] = ce
    env['GIT_COMMITTER_DATE']  = f"{ct} {ctz}"

    cmd = ['git', 'commit-tree', tree, '-m', message]
    if new_tip:
        cmd += ['-p', new_tip]

    result = subprocess.run(cmd, capture_output=True, text=True, env=env)
    new_hash = result.stdout.strip()
    if not new_hash:
        print(f"ERROR at commit {i} ({old_h[:8]}): {result.stderr}", file=sys.stderr)
        sys.exit(1)

    new_tip = new_hash
    if (i + 1) % 10 == 0 or i == len(keep) - 1:
        print(f"  [{i+1:3d}/{len(keep)}] {old_h[:8]} -> {new_hash[:8]}")

print(f"\nDone. New tip: {new_tip}")
with open('rebuild_tip.txt', 'w') as f:
    f.write(new_tip)
print("Tip written to rebuild_tip.txt")
