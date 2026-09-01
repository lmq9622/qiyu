# -*- coding: utf-8 -*-
"""Phase B 收尾审计：扫描测试用户历史里的额外消息（webcheck 回填 / nudge / reminder / 主动消息），
验证：工具回填是否带真实结果、主动消息是否自然、有无重复/串台。"""
import json, io, sys, re
import httpx
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
BASE = "http://127.0.0.1:8766"
rows = [json.loads(l) for l in open('test_harness/report/results_personas_runB.jsonl', encoding='utf-8') if l.strip()]
client = httpx.Client(timeout=20)
stats = {"extra_assistant": 0, "with_url": 0, "checked": 0}
samples = []
seen_users = {}
for r in rows:
    uid = f"e2e_p_{r['persona']}_{r['id']}_{r['iter']}"
    cid = r['persona']
    if uid in seen_users:
        continue
    seen_users[uid] = True
    try:
        h = client.get(f"{BASE}/v1/chat/history", params={"user_id": uid, "char_id": cid, "limit": 50}, timeout=15).json()
        msgs = h.get("messages") or h.get("data") or h
        if isinstance(msgs, dict):
            msgs = msgs.get("messages") or []
        asst = [m for m in msgs if (m.get("role") == "assistant" and (m.get("content") or "").strip())]
        if len(asst) > 1:
            extra = asst[1:]
            stats["extra_assistant"] += len(extra)
            stats["checked"] += 1
            for m in extra:
                c = (m.get("content") or "").strip()
                if re.search(r"https?://", c):
                    stats["with_url"] += 1
                samples.append((r['pname'], r['id'], r['iter'], c[:160]))
    except Exception:
        pass
dup = 0
for i in range(len(samples)-1):
    a = samples[i][3]; b = samples[i+1][3]
    if a and b and len(a) > 8 and (a in b or b in a):
        dup += 1
stats["dup_text"] = dup
print(json.dumps(stats, ensure_ascii=False, indent=1))
print("--- 额外消息样本（前 25）---")
for s in samples[:25]:
    print(f"{s[0]}·{s[1]} iter{s[2]}: {s[3]}")