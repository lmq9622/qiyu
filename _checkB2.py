import json, io, sys
from collections import Counter, defaultdict
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
rows = [json.loads(l) for l in open('test_harness/report/results_personas_runB.jsonl', encoding='utf-8') if l.strip()]
print('rows:', len(rows), 'ok:', sum(1 for r in rows if r.get('ok')))
fails = [r for r in rows if not r.get('ok')]
print('fails:', len(fails))
for r in fails[:10]:
    print(' ', r['pname'], r['id'], 'iter', r['iter'], 'err', str(r.get('error'))[:60], 'issues', (r.get('score') or {}).get('issues'))
# per-cat progress
cats = Counter(r['id'] for r in rows)
print('scenario coverage:', dict(sorted(cats.items())))
