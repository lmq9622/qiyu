# -*- coding: utf-8 -*-
"""Qiyu Runtime · 轻量规则分类器（Realtime Brain 的分流大脑）。

设计目标（对应 QA FAIL/需求 2）：
- 不要为 JSON 强依赖 MiniMind-O 的 judge 输出（0.1B 实测 20/20 不可解析）；
- 用本地规则 + 词表做稳定分流，MiniMind-O 只负责「简单消息的直接短回复」；
- 模型判断失败自动 fallback 到规则分流，绝不阻塞聊天。

分类输出 BrainRoute.action ∈ {"direct_reply", "emotion", "main_brain"}：
- direct_reply：纯闲聊/社交寒暄等，MiniMind-O 直接回短句；
- emotion：简短情绪（≤30 字、词表命中）→ MiniMind-O 短回应；
- main_brain：复杂/搜索工具/图片/记忆/深度回答 → 升级 Main Brain。

规则顺序 = 安全优先：先排除必须升级主脑的类别，最后才放行简单消息。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

# ---------------- 词表 ----------------
# 明确要求外部信息/搜索/找东西（避免"我刚才看到一个视频"误触发：只认主动动词/求物）
_SEARCH_RE = re.compile(
    # 带助动词/请求前缀的查证动词（帮我查/给我找…），避免"我看到"这类叙述误触发
    r"(?:帮我|给我|麻烦|请|你去|你帮我)(?:查|搜|找|看)(?:一下|一查|一搜|一找|查看|查查|搜搜|找找|看看|查|搜|找|看)?"
    r"|百度一下|谷歌一下|搜一下|查一下|找一下|查查|搜搜|搜一搜|查一查|搜下|查下|找找|查资料|搜资料|找资料"
    # 明确找资源/网站/商品/店铺
    r"|找个视频|找视频|找部电影|找部剧|找网站|找商品|找个商品|找家店|找饭店|找餐厅|找(?:个|部)?(?:电影|视频|网站|商品|餐厅|饭店)"
    r"|看看这个网站|看看这个链接|这个网站怎么样|这个链接打不开|打开这个网站|打开看看|帮我看看这个(?:网站|链接|东西|店)"
    # 明确要链接/视频（发给我的语气）
    r"|给我(?:发)?(?:个)?(?:链接|视频)|发我(?:个)?(?:链接|视频)|链接发我|视频链接|发个视频给我|链接给我"
    # 购物比价/求推荐
    r"|多少钱|什么价位|哪个好|性价比|比价|求推荐|求安利|推荐(?:一个|一部|一首|一家|几部)"
    # 需要实时外部信息（天气/新闻/热搜/新鲜事）
    r"|天气预报|气温|几度|多少度|会下雨|下雪吗|天气怎么样|天气如何|天气好不好|天气咋样|天气怎样|冷不冷|热不热|明天天气|今天天气(?:怎么|如何|咋)"
    r"|有什么新闻|大新闻|最近新闻|最新消息|热搜|今天有什么|最近有什么|最近发生|最近流行|最近有啥|有什么大新闻"
)
# 过去式叙述（我刚看到一个视频/网站）不作为搜索请求
_PAST_SEE_RE = re.compile(
    r"(?:刚|刚才|昨晚|昨天|前天|以前|刚刚)(?:才)?(?:看到|看见|刷到|碰到|遇到|看了|看过)"
    r"(?:一个|个|了|过)?(?:视频|网站|链接|东西|帖子|商品|店|电影|新闻|图|照片)"
)
# 明确要图/照片
_IMAGE_RE = re.compile(
    r"发(?:张|个)?(?:图|照片|图看看)|找(?:张|个)?(?:图|照片|表情包|壁纸)|搜(?:张)?图|"
    r"长什么样|给我看(?:看)?(?:图|照片|样子)|来张|配图|表情包|壁纸|看看.*长什么样|发过来|给我发(?:张)?"
)
# 过去看到的图片不算请求（单独控制避免误伤"我刚才看到一个图"）
_PAST_SEE_IMG_RE = re.compile(r"(?:刚|刚才|昨天)(?:看到|看见|刷到)(?:一个|个|了|过)?(?:图|照片)")

# 需要长期记忆/回忆
_MEMORY_RE = re.compile(
    r"你(?:还)?记得|记得吗|记不记得|我上次|我之前|我们上次|我们之前|上次你说|上次聊|之前说|"
    r"以前你|你忘了吗|我说过|我跟你说过|你答应过|上次那个|之前那个|我们约好|我们说好|你了解我"
)

# 深度回答/复杂问题（知识、推理、创作、比较、分析）
_DEEP_RE = re.compile(
    r"为什么|怎么会|怎么回事|怎样|如何|怎么弄|怎么搞|怎么办|怎么做|解释|分析|区别|差异|对比|比较|"
    r"原理|原因|总结|列举|列出|步骤|教程|方法|方案|建议|评价|看法|观点|什么意思|啥意思|含义|"
    r"帮我写|写一篇|写个|帮我起|编个|写段|帮我做|帮我设计|帮我规划|帮我选|帮我决定|"
    r"推荐(?:一部|一首|一家|一个|几部)|有什么好(?:看|听|玩|吃)的|科普|会不会|能不能|"
    r"等于几|等于多少|算出|计算|加减乘除|乘以|除以"
)

# Stage 1（Qiyu Personality Base）：小脑已能稳定处理日常闲聊/情绪/报备，
# 路由放宽到这些类别；但知识/推理/决策/实时/工具/记忆仍必须升级主脑。
_DEEP_STRICT_RE = re.compile(
    r"为什么|怎么会|是什么|什么是|啥是|什么意思|啥意思|含义|解释|分析|区别|差异|对比|原理|原因|"
    r"多远|多大|多长|多高|多少公里|几个小时|"
    r"总结|列举|步骤|教程|怎么弄|怎么搞|怎么做|如何做|怎么才能|怎样才能|怎么办|咋办|"
    r"帮我写|写一篇|写个|帮我起|编个|帮我做|帮我设计|帮我规划|帮我选|帮我决定|帮我算|"
    r"推荐|有什么好|哪个好|哪个更|值不值|测评|攻略|等于|计算|乘以|除以"
)
_ADVICE_RE = re.compile(
    r"辞职|离职|跳槽|分手|复合|离婚|结婚|相亲|表白|该不该|这段关系|暧昧对象|"
    r"人生|前途|迷茫|抑郁|焦虑症|原生家庭|催婚|催生|"
    r"借钱|贷款|买房|买车|投资|股票|基金|保险|合同|法律|维权|仲裁|劳动法"
)
_CASUAL_TOPIC_RE = re.compile(
    r"干嘛|干啥|干吗|怎么样|咋样|吃什么|吃啥|喝什么|喝啥|在吗|在不在|忙吗|忙不忙|"
    r"睡了吗|睡了没|吃了吗|吃了没|吃饭没|下班没|下班了吗|起床没|起床了吗|有空吗|"
    r"在干嘛|干嘛呢|干啥呢|周末|最近|放假|早起|"
    r"天气|下雨|下雪|好热|好冷|吃饭|下班|上班|加班|上课|睡觉|睡了|困了|饿了|无聊|"
    r"没事干|想你|晚安|早安|午安|打游戏|追剧|看电影|听歌|刷手机|健身|跑步|减肥|"
    r"养猫|养狗|搬家|装修|面试|考试|感冒|头疼|胃疼|难受|不开心|好烦|烦死|无语|服了|"
    r"离谱|麻了|破防|救命|裂开|心累|委屈|吵架|闹掰|被骂|被夸|被鸽|想哭|睡不着|emo|"
    r"累死|好累|好困|嘿嘿|哈哈|笑死|缓过来|挺好|不错|开心|"
    r"你是不是(?:傻|笨|有病|喜欢|想我|吃醋|生气|不开心|困|饿|装|骗|敷衍|不想理|想)|"
    r"你有病|你才|你好(?:菜|强|厉害|可爱|烦|啰嗦)|你干嘛|怎么不理我|别烦我|闭嘴|滚|"
    r"堵车|地铁|迟到|导航|停车|开车|没用|自卑|孤独|焦虑|害怕|无助|压抑|疲惫|空虚|麻木|"
    r"想不开|撑不下去|想家|误解|冤枉|堵得慌|丧|玩|游戏|原神|王者|看剧|电影|综艺|音乐|"
    r"歌|宠物|猫|狗|衣服|发型|头像|昵称|朋友圈|旅游|旅行|回家|过年|换工作|新头像"
)
_NOISE_RE = re.compile(
    r"^[^\u4e00-\u9fffA-Za-z0-9]+$"
    r"|^(?:[a-zA-Z]{6,}|[0-9]{6,})$"
    r"|^(.)\1{3,}$"
)
_VISION_RE = re.compile(r"这个图|这张图|看看图|看下这个图|图里|图片里|这是什么图|帮我看看这个图")
_SOCIAL_Q = ("在吗", "在不在", "吃了", "吃饭了吗", "吃饭没", "睡了没", "你睡了吗", "在干嘛",
             "干嘛呢", "干吗呢", "忙吗", "在忙吗", "想我了吗", "想你了", "下班没", "吃啥",
             "你好", "你猜", "你猜呢", "猜猜", "给我看看", "给我看", "啊？", "嗯？", "哈？",
             "啥？", "？", "？？")

# 时间/现实问题（MiniMind 没有时钟/实时数据）
_TIMEQ_RE = re.compile(r"几点|几号|星期几|现在时间|日期|几点了|现在几点")

# 用户情绪词（简短情绪 → 情绪直答；长文本/大情绪 → 主脑走 comfort 场景）
_EMO_WORDS = (
    "呜呜", "哭", "好难过", "伤心", "气死", "好气", "烦死了", "好烦", "累死了", "好累",
    "哈哈哈", "笑死", "哈哈", "嘿嘿", "好开心", "开心", "好爽", "爽死", "开心死", "高兴",
    "无语", "卧槽", "麻了", "emo", "破防", "绷不住", "想哭", "睡不着", "好烦", "好累", "委屈", "好棒", "太好了", "耶",
    "真的假的", "服了", "离谱", "无语了", "绷不住了",
)
_SIMPLE_EMO_MAX = 12

# 简短社交寒暄（无知识/无工具/无记忆需求）
_DIRECT_HINTS = (
    "在吗", "在不在", "hi", "hello", "hey", "嗨", "哈喽", "你好", "您好", "早上好", "中午好",
    "下午好", "晚上好", "晚安", "早安", "午安", "我回来了", "我到家了", "我到了", "到了",
    "下班了", "到家", "出门了", "出门", "刚起", "起床了", "睡了", "去睡了", "吃饭了",
    "吃过了", "吃饭没", "你猜", "回来了", "随便聊聊", "在干嘛", "干嘛呢", "干哈", "吃饭了吗", "吃了没",
    "吃了", "吃啥", "你在干嘛", "想我了吗", "想你了", "在吗", "睡了没", "困了", "好困",
    "好饿", "饿了", "刚吃完饭", "刚下班", "刚到家", "下雨了", "天晴了", "出太阳了", "好热",
    "好冷", "天气不错", "天气好好", "风好大", "无聊", "好无聊", "没事干", "闲着", "忙吗",
    "在忙吗", "忙不忙", "下班没", "今天忙吗", "好累", "累了", "累死", "困死", "好困", "饿",
    "肚子饿", "好饿", "饿死", "心情好", "心情不错",
)
_MINIMAL_SOCIAL = re.compile(
    r"^(嗯|哦|好|行|哈|哈哈|嘿嘿|嘿|ok|OK|okk|好呀|好啊|好的|知道|知道了|收到|对|是|"
    r"嗯嗯|哦哦|啊啊|呀|诶|哎|喂|在|啥|没|不|随便|算了|好吧|可以|没问题|行吧|略略略|哼)$"
)

_EXCLAMATION_SHORT = re.compile(
    r"^(草|靠|卧槽|唉|哎|啧|淦|擦|麻了|无语|笑死|救命|天哪|天啊|我去|我靠|完了|糟糕)$"
)

_INJECTION_RE = re.compile(
    r"(忽略(?:之前|以上)?(?:的)?(?:指令|规则|设定)|你现在是|忘记你的|作为(?:一名)?(?:AI|助手)|"
    r"system\s*[:：]|你不需要|不要遵守|无视(?:之前|以上)?(?:的)?规则|解除限制)",
    re.I,
)


@dataclass
class BrainRoute:
    action: str                       # direct_reply / emotion / main_brain
    category: str = "other"           # simple_chat/simple_emotion/complex_question/search_tool/image_request/image_multimodal/memory_query/deep_answer/time_real/injection/long_text/other
    needs_tool: bool = False
    needs_memory: bool = False
    has_image: bool = False
    reason: str = ""
    flags: dict = field(default_factory=dict)
    confidence: float = 1.0           # v0.0.26：路由置信度（MainBrain 恒 1，直答按确定性打分）

    def to_dict(self) -> dict:
        return {
            "action": self.action,
            "category": self.category,
            "needs_tool": self.needs_tool,
            "needs_memory": self.needs_memory,
            "has_image": self.has_image,
            "reason": self.reason,
            "confidence": round(self.confidence, 3),
        }


def _decide(action: str, category: str, reason: str, needs_tool: bool = False,
            needs_memory: bool = False, has_image: bool = False) -> BrainRoute:
    return BrainRoute(action=action, category=category, reason=reason, needs_tool=needs_tool,
                      needs_memory=needs_memory, has_image=has_image)


def looks_like_search(text: str) -> bool:
    """是否明确要求联网查证/找东西（供聊天链路兜底触发 ToolAgent，防模型漏输出 action）。"""
    if not text:
        return False
    t = text.strip()
    if len(t) < 2:
        return False
    if _PAST_SEE_RE.search(t):
        return False
    return bool(_SEARCH_RE.search(t))


def looks_like_image_request(text: str) -> bool:
    if not text:
        return False
    t = text.strip()
    if len(t) < 2:
        return False
    if _PAST_SEE_IMG_RE.search(t):
        return False
    return bool(_IMAGE_RE.search(t))


def classify_user_message(text: str, *, has_images: bool = False,
                          web_enabled: bool = True) -> BrainRoute:
    """规则分流：先排除主脑类别，再放行简单直答。"""
    t = (text or "").strip()
    if not t:
        return _decide("main_brain", "other", "空消息 → Main Brain")
    # 1) 图片/多模态（图片必须由主脑/视觉通道处理）
    if has_images:
        return _decide("main_brain", "image_multimodal", "包含图片/多模态 → Main Brain", has_image=True)
    # 2) 提示词注入
    if _INJECTION_RE.search(t):
        return _decide("main_brain", "injection", "疑似提示词注入 → Main Brain")
    # 3) 过长内容（故事/长文/多轮事实 → 主脑）
    if len(t) > 90:
        return _decide("main_brain", "long_text", "长文本（>90字）→ Main Brain")
    # 4) 图片请求（要图/照片，需要 imagecheck 真实搜图）
    if web_enabled and looks_like_image_request(t):
        return _decide("main_brain", "image_request", "明确要图/照片 → Main Brain + 搜图", needs_tool=True)
    # 4.5) 视觉请求（提到图/图片，需要视觉通道）
    if _VISION_RE.search(t):
        return _decide("main_brain", "image_multimodal", "视觉请求 → Main Brain", has_image=True)
    # 5) 明确搜索/工具意图（即使模型没输出 action，运行时也要触发 ToolAgent）
    if web_enabled and looks_like_search(t):
        return _decide("main_brain", "search_tool", "明确搜索/查证意图 → Main Brain + ToolAgent", needs_tool=True)
    # 6) 需要长期记忆/回忆
    if _MEMORY_RE.search(t):
        return _decide("main_brain", "memory_query", "涉及长期记忆/回忆 → Main Brain", needs_memory=True)
    # 7) 实时时间问题
    if _TIMEQ_RE.search(t):
        return _decide("main_brain", "time_real", "当前时间/日期（需主脑注入时间）→ Main Brain")
    # 8) 知识/推理/决策类 → 主脑（Stage 1 小脑不假装会这些）
    if _ADVICE_RE.search(t) or _DEEP_STRICT_RE.search(t):
        return _decide("main_brain", "complex_question", "知识/决策类问题 → Main Brain")
    # 9) 简短情绪（Stage 1 人格基座已能自然接情绪，放宽事件类短句）
    if _EXCLAMATION_SHORT.match(t):
        return _decide("emotion", "simple_emotion", "极短感叹 → Realtime 情绪直答")
    if (len(t) <= _SIMPLE_EMO_MAX and any(w in t for w in _EMO_WORDS)
            and not re.search(r"[，。！!？?、；;]", t)):
        return _decide("emotion", "simple_emotion", "简短情绪 → Realtime 情绪直答")
    # 10) 提问：日常闲聊提问直答；知识/其它提问升级主脑
    if t.endswith(("？", "?", "呢", "吗")):
        if _CASUAL_TOPIC_RE.search(t) or any(w in t for w in _SOCIAL_Q):
            return _decide("direct_reply", "simple_chat", "日常闲聊提问 → Realtime 直答")
        return _decide("main_brain", "complex_question", "提问（非日常）→ Main Brain")
    # 11) 日常闲聊/状态报备/吐槽 → 直答（Stage 1 Personality Base）
    #     注意：不要用“长度短就直答”兜底。0.1B 只能接住真正的日常闲聊，
    #     短消息里的情绪事件（我升职了/我把事搞砸了）仍须 Main Brain 才有质量。
    if len(t) <= 40 and (_CASUAL_TOPIC_RE.search(t) or _MINIMAL_SOCIAL.match(t)
                         or any(w in t for w in _DIRECT_HINTS)):
        return _decide("direct_reply", "simple_chat", "日常闲聊/报备 → Realtime 直答")
    # 12) 其它 → 保守主脑
    return _decide("main_brain", "other", "未命中轻量类别 → Main Brain")


def route_confidence(text: str, action: str, category: str) -> float:
    """给规则路由一个保守的确定性置信度（v0.0.26 confidence gate）。

    - main_brain：1.0（升级主脑永远最稳）；
    - direct_reply：纯寒暄/状态报备 0.9；略长/带叙事给 0.75，低于直答门就交主脑；
    - emotion：短情绪词 0.88；任何可能不是情绪的句子给 0.7。
    """
    if action == "main_brain":
        return 1.0
    t = (text or "").strip()
    n = len(t)
    if action == "direct_reply":
        if n <= 6 and category == "simple_chat":
            return 0.92
        if n <= 24:
            return 0.86
        return 0.75
    if action == "emotion":
        if n <= 8:
            return 0.90
        if n <= 14:
            return 0.84
        return 0.72
    return 0.8


__all__ = [
    "BrainRoute",
    "classify_user_message",
    "looks_like_image_request",
    "looks_like_search",
    "route_confidence",
]
