# -*- coding: utf-8 -*-
"""真人感深度分析：从 results.jsonl 挑出疑似 AI 味 / 模板 / 过度热情的样本"""
import json, re, sys
from collections import Counter, defaultdict

AI_ISMS_EXTRA = {
    "好呀": 2, "呢": 0.5, "啦": 0.8, "呀": 0.5, "哦": 0.5, "嘛": 0.8, "叭": 1.5, "嘞": 1.5,
    "哒": 1.5, "呐": 1.5, "咯": 1.5, "耶": 1.5, "么么": 2, "抱抱": 2, "嘿嘿": 1, "嘻嘻": 1.2,
    "哈哈": 0.6, "绝了": 1.5, "馋馋": 3, "云吃": 3, "陪着你": 3, "一直都在": 3, "不管发生什么": 3,
    "需要我帮": 3, "有什么可以帮": 3, "我来帮你": 2, "如果需要": 2, "没关系哦": 2, "别担心": 2,
    "加油哦": 2, "好的呢": 2, "可以呢": 2, "没问题哦": 2, "您": 1.5, "主人": 4, "宝宝": 2.5,
    "宝贝": 2.5, "亲爱的": 2.5, "亲爱滴": 2.5,
}
TEMPLATE_PATTERNS = [
    (r"有什么想[跟和]我|想聊什么|想说什么", "引导对话模板"),
    (r"需要我帮你|有什么需要|如果需要我", "帮助选项模板"),
    (r"我(?:会|可以)(?:一直|永远|随时)", "永远陪伴模板"),
    (r"不管(?:发生什么|什么时候)|无论如何", "无条件承诺模板"),
    (r"加油[！!]|相信你|你一定可以", "加油模板"),
    (r"记得(?:好好|按时|早点|多喝)", "叮嘱模板"),
    (r"希望你能|愿你", "祝愿模板"),
    (r"今天过得怎么样|最近过得怎么样", "问候模板"),
    (r"是不是(?:心情|不开心|很累|烦)", "猜测情绪模板"),
    (r"你(?:真|太)(?:可爱|有趣|幽默)", "彩虹屁模板"),
    (r"有时间(?:的话)?(?:再|就)", "客套模板"),
    (r"我们一起|我们一起加油", "一起模板"),
    (r"嗯嗯嗯|对对对|好好好", "敷衍叠字"),
    (r"哈哈哈哈哈|嘿嘿嘿嘿|嘻嘻嘻", "叠哈"),
    (r"！！！|！！|？？？|？？", "标点轰炸"),
    (r"[，,]\s*[，,]", "连续逗号"),
]
EVIDENCE_RE = re.compile(r"(https?://|结果为|根据搜索|查到了|搜到|找到了|价格[是为]|元/|¥)")
FACT_RE = re.compile(r"[0-9]+(\s*(元|块|美元|美金|年|月|日|号|万|点|GB|TB|km|公里))")

def analyze(rows):
    report = []
    by_cat = defaultdict(list)
    for r in rows:
        texts = [p["text"] for t in r.get("turns", []) for p in t.get("pieces", []) if p.get("text")]
        joined = "".join(texts)
        ai_score = sum(0 for _ in [])  # 累计
        ai_terms = Counter()
        for w, wgt in AI_ISMS_EXTRA.items():
            c = joined.count(w)
            if c:
                ai_terms[w] = c
        ai_score = sum(c * wgt for w, c in ai_terms.items())
        issues = []
        for pat, name in TEMPLATE_PATTERNS:
            if re.search(pat, joined):
                issues.append(name)
        # 单条过长
        long_msgs = [t for t in texts if len(t) > 120]
        if long_msgs:
            issues.append(f"长消息x{len(long_msgs)}")
        # 消息条数过多
        if len(texts) >= 5:
            issues.append(f"条数x{len(texts)}")
        # emoji 刷屏
        emo = [len(re.findall(r"[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U0001F900-\U0001F9FF\u2B00-\u2BFF\uFE0F]", t)) for t in texts]
        if any(e >= 3 for e in emo):
            issues.append(f"emoji刷屏:{emo}")
        # 工具场景：无证据但有具体事实数字
        if r.get("cat") == "tool" and not r.get("tool_done"):
            facts = FACT_RE.findall(joined)
            if facts and not EVIDENCE_RE.search(joined):
                issues.append(f"疑似编造事实:{facts[:3]}")
        if ai_score > 0 or issues:
            by_cat[r["cat"]].append((r["id"], r["char"], ai_score, issues, texts, joined))
    return by_cat, ai_terms

def main(path, topn=40):
    rows = [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]
    by_cat, _ = analyze(rows)
    print(f"总轮次 {len(rows)}，以下按类别列出 AI 味/模板样本（最多 topn 条）")
    # 排序：按类别内 ai_score+问题数排序
    for cat in sorted(by_cat, key=lambda c: -len(by_cat[c])):
        items = by_cat[cat]
        items.sort(key=lambda x: (-x[2], -len(x[3])))
        print(f"\n########## [{cat}] 命中 {len(items)} ##########")
        for sid, ch, sc, iss, texts, joined in items[:min(topn, len(items))]:
            print(f"--- {sid} {ch} ai={sc} issues={iss}")
            for t in texts:
                print(f"    {t}")

if __name__ == "__main__":
    main("report/results.jsonl" if len(sys.argv) < 2 else sys.argv[1])
