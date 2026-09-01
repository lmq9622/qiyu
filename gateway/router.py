"""
栖语 (Qiyu) - 配置化意图路由模块
从 YAML 加载规则，支持热重载
"""

import re
from typing import Optional, List
from dataclasses import dataclass, field
from enum import Enum

from loguru import logger

# 导入配置管理器
try:
    from config import get_config
    CONFIG_AVAILABLE = True
except ImportError:
    CONFIG_AVAILABLE = False


class IntentType(str, Enum):
    CHAT = "chat"
    RAG_QUERY = "rag"
    MEMORY_QUERY = "memory"
    TOOL_CALL = "tool"
    EMOTION = "emotion"
    GREETING = "greeting"
    WEB = "web"


@dataclass
class RouteResult:
    intent: IntentType = IntentType.CHAT
    keywords: list[str] = field(default_factory=list)
    entities: dict[str, str] = field(default_factory=dict)
    needs_rag: bool = False
    needs_memory: bool = False
    needs_web: bool = False
    tool_name: Optional[str] = None
    confidence: float = 0.5
    raw_input: str = ""


class ConfigurableRouter:
    """可配置化意图路由器"""
    
    def __init__(self):
        self._rules: list[dict] = []
        self._defaults: dict = {}
        self._advanced: dict = {}
        self._stop_words: set = set()
        self._load_from_config()
    
    def _load_from_config(self):
        """从配置文件加载规则"""
        if not CONFIG_AVAILABLE:
            logger.warning("配置管理器不可用，使用默认规则")
            self._load_defaults()
            return
        
        try:
            cfg = get_config()
            routes = cfg.routes
            
            self._rules = routes.get("rules", [])
            self._defaults = routes.get("defaults", {})
            self._advanced = routes.get("advanced", {})
            self._stop_words = set(self._advanced.get("stop_words", []))
            
            logger.info(f"从配置加载了 {len(self._rules)} 条路由规则")
        except Exception as e:
            logger.error(f"加载路由配置失败: {e}")
            self._load_defaults()
    
    def _load_defaults(self):
        """加载内置默认规则"""
        self._rules = [
            {"id": "greeting", "intent": "greeting", "match_type": "regex",
             "patterns": [r"^(你好|嗨|哈喽|hey|hi|hello|在吗|在不在)", r"^(早上好|中午好|晚上好|晚安)"],
             "confidence": 0.95},
            {"id": "emotion", "intent": "emotion", "match_type": "keyword",
             "keywords": ["难过", "伤心", "累", "压力", "焦虑", "害怕", "担心", "不开心", "郁闷", "烦", "痛苦", "孤独", "无助", "想哭", "绝望", "迷茫", "撑不住"],
             "threshold": 1, "confidence": 0.75},
            {"id": "rag", "intent": "rag", "match_type": "keyword",
             "keywords": ["什么是", "介绍一下", "解释一下", "原理", "概念", "怎么", "如何", "为什么", "方法", "步骤", "教程"],
             "threshold": 1, "confidence": 0.8},
        ]
        self._defaults = {"fallback_intent": "chat", "fallback_confidence": 0.5, "max_keywords": 10}
        self._stop_words = set()
    
    def reload(self):
        """重新加载配置"""
        logger.info("重新加载路由规则...")
        self._load_from_config()
    
    def route(self, user_input: str) -> RouteResult:
        """分析用户输入，按规则匹配"""
        text = user_input.strip()
        result = RouteResult(raw_input=text)
        
        # 提取关键词
        result.keywords = self._extract_keywords(text)
        
        # 按规则匹配（配置文件中已按优先级排序）
        for rule in self._rules:
            matched = self._match_rule(text, rule)
            if matched:
                intent_str = rule.get("intent", "chat")
                try:
                    result.intent = IntentType(intent_str)
                except ValueError:
                    result.intent = IntentType.CHAT
                
                result.confidence = rule.get("confidence", 0.5)
                result.tool_name = rule.get("tool_name")
                
                # 自动设置 needs_rag / needs_memory
                if result.intent == IntentType.RAG_QUERY:
                    result.needs_rag = True
                elif result.intent == IntentType.MEMORY_QUERY:
                    result.needs_memory = True
                elif result.intent == IntentType.EMOTION:
                    result.needs_memory = True
                
                logger.debug(f"规则匹配: {rule.get('id')} -> {intent_str} (置信度: {result.confidence})")
                return result
        
        # 兜底
        fallback = self._defaults.get("fallback_intent", "chat")
        result.intent = IntentType(fallback) if fallback in [e.value for e in IntentType] else IntentType.CHAT
        result.confidence = self._defaults.get("fallback_confidence", 0.5)
        # 联网意图自动识别：带链接 / 明显的查证诉求（保守，避免普通聊天也被联网拖慢）
        if re.search(r"https?://", text) or re.search(
            r"(帮我|给我|麻烦|顺带)?(查|搜)(一下|一查|查看|一搜|搜|查)?|百度一下|谷歌一下|查查看|搜搜|查查|去查|去搜|看看最近|热搜|今天有什么新闻|最近发生|最新消息|今日",
            text,
        ):
            result.needs_web = True
            if result.intent == IntentType.CHAT:
                result.intent = IntentType.WEB
        return result
    
    def _match_rule(self, text: str, rule: dict) -> bool:
        """单条规则匹配"""
        match_type = rule.get("match_type", "keyword")
        
        if match_type == "keyword":
            keywords = rule.get("keywords", [])
            threshold = rule.get("threshold", 1)
            hit_count = sum(1 for kw in keywords if kw in text)
            return hit_count >= threshold
        
        elif match_type == "regex":
            patterns = rule.get("patterns", [])
            for pattern in patterns:
                try:
                    if re.search(pattern, text):
                        return True
                except re.error as e:
                    logger.warning(f"正则表达式错误 [{rule.get('id')}]: {e}")
            return False
        
        return False
    
    def _extract_keywords(self, text: str) -> list[str]:
        """关键词提取"""
        words = re.findall(r'[\u4e00-\u9fff]+|[a-zA-Z]+', text)
        max_kw = self._defaults.get("max_keywords", 10)
        keywords = [w for w in words if len(w) >= 2 and w not in self._stop_words]
        return list(set(keywords))[:max_kw]


# 全局路由器（兼容旧接口）
_old_router = None
_configurable_router = None


def get_router():
    """获取路由器（优先返回配置化版本）"""
    global _configurable_router
    if _configurable_router is None:
        _configurable_router = ConfigurableRouter()
    return _configurable_router


# 测试
if __name__ == "__main__":
    router = get_router()
    
    test_inputs = [
        "你好",
        "我好难过，工作压力好大",
        "什么是量子计算？",
        "你记得我之前说的那个项目吗？",
        "帮我记住我的生日是3月15日",
        "今天天气不错",
    ]
    
    print("=" * 60)
    for text in test_inputs:
        result = router.route(text)
        print(f"\n输入: {text}")
        print(f"  意图: {result.intent.value} (置信度: {result.confidence:.2f})")
        print(f"  关键词: {result.keywords}")
        print(f"  RAG: {result.needs_rag}, 记忆: {result.needs_memory}, 工具: {result.tool_name}")
    print("=" * 60)
    
    # 测试配置热重载
    print("\n测试热重载...")
    router.reload()
