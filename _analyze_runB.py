# -*- coding: utf-8 -*-
"""Phase B 深度分析：真人感亮点/不足/按人设按场景/记忆/工具/表情/时长统计。"""
import json, io, sys, re, time
from collections import Counter, defaultdict
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
rows = [json.loads(l) for l in open('test_harness/report/results_personas_runB.jsonl', encoding='utf-8') if l.strip()]
ok = sum(1 for r in rows if r.get('ok'))
print(f"== 总览: {len(rows)} 次 / 通过 {ok} / 失败 {len(rows)-ok} ==")
# 按人设
byp = defaultdict(lambda: [0,0])
for r in rows:
    byp[r['pname']][0] += 1; byp[r['pname']][1] += 1 if r.get('ok') else 0
for n,(t,o) in sorted(byp.items()):
    print(f"  {n}: {o}/{t}")
# 按场景
bys = defaultdict(lambda: [0,0])
for r in rows:
    bys[r['id']][0] += 1; bys[r['id']][1] += 1 if r.get('ok') else 0
for n,(t,o) in sorted(bys.items()):
    print(f"  {n}: {o}/{t}")
# issues 分类
iss = Counter()
for r in rows:
    for it in (r.get('score') or {}).get('issues', []):
        iss[it.split(':')[0]] += 1
print("issues:", dict(iss.most_common(10)))
# 消息长度分布（单次回复总字符）
lens = [sum(len(x['text']) for x in t.get('pieces',[]) if x.get('text')) for r in rows for t in r['turns']]
if lens:
    print(f"回复长度: 中位 {sorted(lens)[len(lens)//2]} 平均 {sum(lens)/len(lens):.1f} 最大 {max(lens)}")
# 记忆与工具
mem = [r for r in rows if r.get('cat')=='memory']
tool = [r for r in rows if r.get('cat')=='tool']
print(f"记忆写入 {sum(1 for r in mem if (r.get('memory') or {}).get('found'))}/{len(mem)}  调用召回 {sum(1 for r in mem if r.get('recall_hit'))}/{len(mem)}")
print(f"工具真实执行 {sum(1 for r in tool if r.get('tool_done'))}/{len(tool)}")
# 亮点样例（短且无问题）
good = [r for r in rows if r.get('ok') and not (r.get('score') or {}).get('issues')]
good.sort(key=lambda r: sum(len(x['text']) for t in r['turns'] for x in t.get('pieces',[]) if x.get('text')))
print("\n== 亮点样例（最短 6 条）==")
for r in good[:6]:
    chat = []
    for t in r['turns']:
        chat.append(f"用户: {t['user']}")
        for p in t.get('pieces', []):
            if p.get('text'): chat.append(f"{r['pname']}: {p['text']}")
    print("\n" + "\n".join(chat[:8]))