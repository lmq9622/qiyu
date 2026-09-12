# -*- coding: utf-8 -*-
"""首轮反应安全门：把 MiniMind 的短输出限制在正确的反应语义内。

MiniMind 只负责生成“首轮反应/接话/打断”。0.1B MoE 的生成能力有限，
如果输出不属于当前输入场景的合法反应（例如“嗯 → 啥”“草 → 你才呢”），
这里直接回退到该场景的反应池，避免再次出现“已读乱回”。
反应池本身有多种表达，不会固定成同一句。
"""
from __future__ import annotations

import random
import re

INTENT_BANKS: dict[str, list[str]] = {
    "ack": ["嗯", "哦", "行", "好", "知道了", "收到", "嗯嗯", "好嘞", "行吧"],
    "laugh": ["哈哈", "笑啥", "这么好笑", "你又开始了", "啥梗", "至于吗", "笑死"],
    "annoyed": ["咋了", "又咋了", "谁惹你了", "别烦", "消消气", "说说", "别气"],
    "tired": ["睡吧", "歇会", "别熬了", "早点睡", "去眯会", "躺会", "别硬撑"],
    "question": ["我想想", "这个啊", "等下", "我看看", "让我捋捋", "好问题"],
    "task": ["行", "收到", "我看看", "等下", "马上", "好嘞"],
    "listen": ["我在听", "然后呢", "后来呢", "你继续", "嗯嗯", "听着呢"],
    "interrupt": ["你说", "好你说", "你讲", "我听着", "你先说"],
    "repair": ["啊？", "啥", "没懂", "你说啥", "没听清", "再来一遍"],
    "banter": ["你才", "少来", "有病吧", "嘿嘿", "你完了", "行行行"],
    "miss": ["肉麻", "咋突然", "少来", "我也想你", "行吧"],
    "emotion": ["咋了", "怎么了", "谁惹你了", "我在", "别憋着", "抱一下", "说说"],
    "greet": ["早", "晚安", "在", "嗯", "好", "哈喽", "来啦"],
}

_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("interrupt", re.compile(r"等等|停一下|打住|我先说|你别说了|我插一句|打断|你先听|"
                             r"我还没说完|让我说完|你先别|你先停|先听我")),
    ("repair", re.compile(r"打错|没听清|阿巴阿巴|啥玩意儿|没懂|再说一遍|手滑|重说|"
                          r"没看懂|打岔|语音识别|表达.*乱|重新说")),
    ("listen", re.compile(r"我昨天遇到|我跟你说|你听我说|我跟你讲|事情是这样的|我有个事|"
                          r"我最近|我遇到|你听我慢慢说|我跟你讲个|我有个.*想")),
    ("task", re.compile(r"帮我|给我|替我|麻烦|去查|去搜|找一下|查一下|搜一下|写个|写一篇|"
                        r"做个|讲个|推荐|安排|翻译|总结|列个|规划|算一下")),
    ("banter", re.compile(r"你有病|你是不是|少来|牛啊|牛啊|离谱|傻|滚|闭嘴|绝了")),
    ("annoyed", re.compile(r"草|烦|无语|服了|离谱|麻了|破防|裂开|救命|气死|醉了|会谢|"
                           r"绷不住|受不了")),
    ("tired", re.compile(r"困|累|睡|熬夜|乏|撑不住|熬不动|没精神")),
    ("laugh", re.compile(r"哈哈|笑死|笑不活|绷不住|乐死|嘿嘿|呵呵|乐死")),
    ("miss", re.compile(r"想你|想我|想不想")),
    ("greet", re.compile(r"在吗|早安|晚安|哈喽|hello|hi|嗨|吃了吗|睡了没|起床没|在不在")),
    ("question", re.compile(r"[？?]$|吗$|呢$|^什么|^怎么|^为啥|^为什么|^如何|^哪个|^多少|"
                            r"是不是|能不能|可不可以|该不该|值不值|靠谱吗|怎么办")),
    ("emotion", re.compile(r"难过|伤心|委屈|想哭|不开心|心情|焦虑|孤独|想家|堵|怕|难受|emo|丧|"
                           r"讨厌|自责|后悔")),
    ("ack", re.compile(r"^(嗯|哦|好|行|可以|收到|知道了|懂了|ok|OK|嗯嗯|哦哦|好嘞|行吧)")),
]


def classify_reaction_intent(user_text: str) -> str:
    t = (user_text or "").strip()
    for name, pat in _PATTERNS:
        if pat.search(t):
            return name
    return "ack"


def _is_allowed(text: str, bank: list[str]) -> bool:
    if not text:
        return False
    if len(text) > 6:
        return False
    for x in bank:
        if text == x or text.startswith(x):
            return True
    return False


def normalize_reaction(user_text: str, model_output: str,
                       rng: random.Random | None = None) -> str:
    """模型输出在正确语义内就保留，否则从对应反应池里回退。"""
    intent = classify_reaction_intent(user_text)
    bank = INTENT_BANKS.get(intent) or INTENT_BANKS["ack"]
    text = (model_output or "").strip()
    if _is_allowed(text, bank):
        return text
    r = rng or random
    return r.choice(bank)


__all__ = ["INTENT_BANKS", "classify_reaction_intent", "normalize_reaction"]
