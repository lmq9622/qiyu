"""
栖语 (Qiyu) - Letta Agent 工具扩展
为 Agent 添加 RAG 查询等自定义工具
"""

import os
from typing import List

from dotenv import load_dotenv
from loguru import logger

try:
    from qdrant_client import QdrantClient
    from embedding.service import get_embedding_service
    QDRANT_AVAILABLE = True
except ImportError:
    QDRANT_AVAILABLE = False

load_dotenv()

QDRANT_HOST = os.getenv("QDRANT_HOST", "127.0.0.1")
QDRANT_PORT = int(os.getenv("QDRANT_PORT", "6333"))
QDRANT_RAG_COLLECTION = os.getenv("QDRANT_RAG_COLLECTION", "companion_knowledge")


def rag_search(query: str, top_k: int = 5) -> str:
    """
    从知识库中搜索相关信息
    
    Args:
        query: 搜索查询
        top_k: 返回结果数量
    
    Returns:
        检索到的文本，每条以换行分隔
    """
    if not QDRANT_AVAILABLE:
        return "[知识库未启用]"
    
    try:
        qdrant = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)
        embedding = get_embedding_service()
        
        query_vector = embedding.encode_query(query)
        
        results = qdrant.search(
            collection_name=QDRANT_RAG_COLLECTION,
            query_vector=query_vector,
            limit=top_k,
            with_payload=True,
        )
        
        if not results:
            return "[未找到相关知识]"
        
        texts = []
        for r in results:
            text = r.payload.get("text", "")
            file = r.payload.get("file_name", "")
            if text:
                texts.append(f"[{file}] {text}")
        
        return "\n\n".join(texts)
    
    except Exception as e:
        logger.error(f"RAG 搜索失败: {e}")
        return f"[搜索出错: {str(e)}]"


def save_memory(key: str, value: str) -> str:
    """
    主动保存一条长期记忆到知识库
    
    Args:
        key: 记忆的标题/关键词
        value: 记忆的内容
    
    Returns:
        保存结果
    """
    if not QDRANT_AVAILABLE:
        return "[知识库未启用，记忆未保存]"
    
    try:
        qdrant = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)
        embedding = get_embedding_service()
        
        # 确保 collection 存在
        from qdrant_client.http.models import Distance, VectorParams
        collections = qdrant.get_collections().collections
        collection_names = [c.name for c in collections]
        
        memory_collection = "companion_memory_longterm"
        if memory_collection not in collection_names:
            qdrant.create_collection(
                collection_name=memory_collection,
                vectors_config=VectorParams(size=embedding.dimension, distance=Distance.COSINE),
            )
        
        text = f"{key}: {value}"
        vector = embedding.encode_query(text)
        
        import hashlib
        point_id = hashlib.md5(text.encode()).hexdigest()
        
        from qdrant_client.http.models import PointStruct
        qdrant.upsert(
            collection_name=memory_collection,
            points=[PointStruct(
                id=point_id,
                vector=vector,
                payload={
                    "key": key,
                    "value": value,
                    "text": text,
                    "type": "manual_memory",
                }
            )]
        )
        
        return f"[已记住: {key}]"
    
    except Exception as e:
        logger.error(f"保存记忆失败: {e}")
        return f"[保存失败: {str(e)}]"


# 工具注册表（供 Letta 使用）
TOOLS = {
    "rag_search": rag_search,
    "save_memory": save_memory,
}
