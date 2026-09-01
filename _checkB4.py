import json, io, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
rows = [json.loads(l) for l in open('test_harness/report/results_personas_runB.jsonl', encoding='utf-8') if l.strip()]
for sid in ('s081','s111'):
    t = [r for r in rows if r['id']==sid]
    if not t: continue
    done = sum(1 for r in t if r.get('tool_done'))
    print(sid, 'rows', len(t), 'done', done)
    for r in t:
        print(f"  {r['pname']:10s} iter{r['iter']} done={r.get('tool_done')} followup={r.get('tool_followup')} elapsed={r.get('elapsed')}")
