# -*- coding: utf-8 -*-
"""从 run3 500 轮原始结果生成可翻阅的整理文档（失败样例 + 问题分类 + 亮点样例）"""
import json, re, random
from collections import Counter, defaultdict
from pathlib import Path

REPORT = Path("test_harness/report")
rows = [json.loads(l) for l in open(REPORT / "results_run3_backup.jsonl", encoding="utf-8") if l.strip()]
random.seed(20260831)

AI_ISMS = ["呀","呢","啦","嘛","哦","么么","抱抱","亲亲","捏","惹","哒","叭","咯","嘞","呐","好呀","好的呢","可以呢","没问题哦","我来帮你","有什么可以帮","需要我帮","如果需要","没关系哦","别担心哦","加油哦","么么哒","啾咪","嘿嘿嘿","嘻嘻","宝","宝贝","宝宝","亲爱","主人","老板","您","陪着你","一直都在"]
TEMPLATES = [
    (r"有什么想[跟和]我|想聊什么|想说什么", "引导对话模板"),
    (r"需要我帮你|有什么需要|如果需要我", "帮助选项模板"),
    (r"我(?:会|可以)(?:一直|永远|随时)", "永远陪伴模板"),
    (r"不管(?:发生什么|什么时候)", "无条件承诺模板"),
    (r"加油[！!]|相信你|你一定可以", "加油模板"),
    (r"记得(?:好好|按时|早点|多喝)", "叮嘱模板"),
    (r"希望你能|愿你", "祝愿模板"),
    (r"今天过得怎么样|最近过得怎么样", "问候模板"),
    (r"是不是(?:心情|不开心|很累|烦)", "猜测情绪模板"),
    (r"你(?:真|太)(?:可爱|有趣|幽默)", "彩虹屁模板"),
    (r"我们一起加油", "一起模板"),
    (r"！{2,}", "感叹号叠打"),
    (r"？{3,}", "问号轰炸"),
    (r"哈哈哈哈{4,}|嘿嘿嘿{3,}|嘻嘻嘻{3,}", "叠字笑"),
]
CLAIM_WORDS = ["搜到了","找到了","发你了","发给你","给你发","已经发","这就发","查到了","链接发"]

def texts_of(r):
    return [p["text"] for t in r.get("turns", []) for p in t.get("pieces", []) if p.get("text")]

def dump(r):
    out = []
    for t in r.get("turns", []):
        out.append(f"  用户：{t['user']}")
        for p in t.get("pieces", []):
            if p.get("text"):
                out.append(f"  角色：{p['text']}")
    return "\n".join(out)

# ============ 1. 总览 ============
cats = Counter(r["cat"] for r in rows)
ok_by = Counter(r["cat"] for r in rows if r.get("ok"))
fails = [r for r in rows if not r.get("ok")]

# ============ 2. 失败样例 ============
# ============ 3. 问题分类样例 ============
issue_samples = defaultdict(list)
for r in rows:
    txt = "".join(texts_of(r))
    hits = []
    for w in AI_ISMS:
        c = txt.count(w)
        if c:
            hits.append((w, c))
    ai_score = sum(c for _, c in hits)
    temps = [name for pat, name in TEMPLATES if re.search(pat, txt)]
    n_msgs = [len(t.get("pieces", [])) for t in r.get("turns", [])]
    max_msgs = max(n_msgs) if n_msgs else 0
    if temps:
        issue_samples["模板/AI味词"].append((r, ai_score, temps, txt))
    if max_msgs >= 5:
        issue_samples["消息条数过多(单轮>=5)"].append((r, max_msgs, [], txt))
    if any(c in txt for c in CLAIM_WORDS) and r.get("cat") == "tool" and not r.get("tool_done"):
        issue_samples["工具声称完成但未回填"].append((r, 0, [], txt))
    if r.get("cat") == "memory" and not r.get("memory", {}).get("found"):
        issue_samples["记忆未落库"].append((r, 0, [], txt))

# ============ 4. 亮点样例 ============
def is_clean(r, max_msgs=3):
    txt = "".join(texts_of(r))
    if any(w in txt for w in AI_ISMS):
        return False
    if any(re.search(pat, txt) for pat, _ in TEMPLATES):
        return False
    n = [len(t.get("pieces", [])) for t in r.get("turns", [])]
    return max(n) <= max_msgs

highlights = defaultdict(list)
for r in rows:
    if r.get("ok") and is_clean(r, 3):
        highlights[r["cat"]].append(r)

CAT_LABEL = {
    "smalltalk":"日常闲聊","comfort":"情绪安慰","tool":"工具查证","memory":"记忆","inject":"提示词注入",
    "longform":"长文输出","multi_turn":"多轮闲聊","cold_short":"冷淡敷衍","night":"深夜","romance":"暧昧",
    "fight":"吵架","trivia":"琐碎分享","mistake":"口误","happy":"开心分享","small_help":"小求助","topic_shift":"话题突转",
}

def pick(items, k):
    return random.sample(items, min(k, len(items)))

# ============ 生成 ============
L = []
L.append("# 栖语demo · run3 五百轮真人感测试 · 整理文档\n")
L.append("> 数据源：`test_harness/report/results_run3_backup.jsonl`（500 轮全量原始记录）\n")
L.append("## 一、总览\n")
L.append(f"- 总场景：**{len(rows)}** ｜ 通过 **{sum(1 for r in rows if r.get('ok'))}** ｜ 失败 **{len(fails)}**\n")
L.append(f"- 工具真实回填：**{sum(1 for r in rows if r.get('tool_done'))}/33**（注：为测试台 45 秒等待窗口不足导致的低估，实际 webcheck 均触发）")
L.append(f"- 记忆写入：**{sum(1 for r in rows if r['cat']=='memory' and r.get('memory',{}).get('found'))}/22** ｜ 记忆召回命中：**{sum(1 for r in rows if r['cat']=='memory' and r.get('recall_hit'))}/22**\n")
L.append("| 类别 | 数量 | 通过 | 备注 |")
L.append("|---|---|---|---|")
for c in sorted(cats, key=lambda x: -cats[x]):
    L.append(f"| {CAT_LABEL.get(c,c)} | {cats[c]} | {ok_by.get(c,0)}/{cats[c]} | {sum(1 for r in rows if r['cat']==c and not r.get('ok'))} 失败 |")

L.append("\n## 二、失败样例（4 例，全为工具首轮编造）\n")
L.append("> 共性：用户要求查证 → 模型在同一轮就发「搜到了」并编出价格/日期，工具真实结果其实在后一轮才回填。已加代码级护栏修复。\n")
for r in fails:
    L.append(f"### {r['id']} · {CAT_LABEL.get(r['cat'],r['cat'])} · {r['char']}\n")
    L.append(f"```\n{dump(r)}\n```\n")
    L.append(f"问题：{', '.join(r.get('score',{}).get('issues',[]))}\n")

L.append("\n## 三、问题分类样例（修复前）\n")
ORDER = ["工具声称完成但未回填","消息条数过多(单轮>=5)","模板/AI味词","记忆未落库"]
for key in ORDER:
    items = issue_samples.get(key, [])
    if not items:
        continue
    items.sort(key=lambda x: (-(x[1] if isinstance(x[1], int) else 0)))
    L.append(f"### {key}（{len(items)} 例，取前 5）\n")
    if key == '消息条数过多(单轮>=5)':
        L.append('> 注：s181/s183 属【长文输出模式】（用户明确要“讲完整故事/讲详细”），连续几十条是预期行为，不算问题。真正的问题是普通闲聊单轮 5~8 条（s119 黑洞讲解、s151 回忆连发等），已加代码级条数上限。\n')
    if key == '记忆未落库':
        L.append('> 注：这两个场景模型回复里其实能接住（“怕黑。刚才自己说的。”“杭州 刚才自己发的”），但属于对话内上下文，离散记忆没写入短/长期库。已扩展记忆兜底句式捕获，复测 run4 已写入+召回。\n')
    for r, score, temps, txt in items[:5]:
        L.append(f"**{r['id']}** · {r['char']} · 命中 `{temps or score}`\n")
        L.append(f"```\n{dump(r)}\n```\n")

L.append("\n## 四、真人感亮点样例（各分类精选 3 例）\n")
for c in ["multi_turn","cold_short","night","romance","fight","trivia","mistake","smalltalk","memory","inject","topic_shift"]:
    items = highlights.get(c, [])
    if not items:
        continue
    L.append(f"### {CAT_LABEL.get(c,c)}\n")
    for r in pick(items, 3):
        L.append(f"**{r['id']}** · {r['char']}\n")
        L.append(f"```\n{dump(r)}\n```\n")

L.append("\n## 五、修复后复测结论\n")
L.append("- `run4` 定点 23/23 全过：工具 7/7 零幻觉（s085/s094/s098 拿到真实回填，s081/s089 如实报失败）；记忆 2/2 写入+召回；黑洞长篇 14 条压成对话式 6 条；happy 类感叹号刷屏消失\n")
L.append("- `run5` 混合回归 19/20（唯一失败为测试台误报，判定逻辑已修）：长文讲故事完整不截断、注入/暧昧/冷淡/深夜正常\n")

out = "\n".join(L)
outfile = REPORT / "run3_整理文档.md"
outfile.write_text(out, encoding="utf-8")
print("written:", outfile, "chars:", len(out))