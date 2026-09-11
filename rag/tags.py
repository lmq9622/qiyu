"""
栖语 (Qiyu) - 记忆标签系统
为 Qdrant 向量数据提供标签 CRUD 管理
"""

import os
from typing import List, Optional
from dataclasses import dataclass

from qdrant_client import QdrantClient
from qdrant_client.http.models import Filter, FieldCondition, MatchValue
from dotenv import load_dotenv
from loguru import logger

load_dotenv()

QDRANT_HOST = os.getenv("QDRANT_HOST", "127.0.0.1")
QDRANT_PORT = int(os.getenv("QDRANT_PORT", "6333"))
QDRANT_RAG_COLLECTION = os.getenv("QDRANT_RAG_COLLECTION", "companion_knowledge")


@dataclass
class TaggedMemory:
    """带标签的记忆条目"""
    id: str
    text: str
    file_name: str
    tags: List[str]
    score: float = 0.0


class MemoryTagManager:
    """记忆标签管理器"""
    
    def __init__(self, collection: str = QDRANT_RAG_COLLECTION):
        self.qdrant = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)
        self.collection = collection
    
    # ============ 标签 CRUD ============
    
    def add_tags(self, point_id: str, tags: List[str]) -> bool:
        """为记忆条目添加标签"""
        try:
            # 获取现有标签
            result = self.qdrant.retrieve(
                collection_name=self.collection,
                ids=[point_id],
                with_payload=True,
            )
            if not result:
                logger.warning(f"记忆条目不存在: {point_id}")
                return False
            
            existing_tags = result[0].payload.get("tags", [])
            new_tags = list(set(existing_tags + tags))
            
            # 更新
            self.qdrant.set_payload(
                collection_name=self.collection,
                payload={"tags": new_tags},
                points=[point_id],
            )
            logger.info(f"添加标签成功: {point_id} -> {tags}")
            return True
        except Exception as e:
            logger.error(f"添加标签失败: {e}")
            return False
    
    def remove_tags(self, point_id: str, tags: List[str]) -> bool:
        """移除记忆条目的标签"""
        try:
            result = self.qdrant.retrieve(
                collection_name=self.collection,
                ids=[point_id],
                with_payload=True,
            )
            if not result:
                return False
            
            existing_tags = result[0].payload.get("tags", [])
            new_tags = [t for t in existing_tags if t not in tags]
            
            self.qdrant.set_payload(
                collection_name=self.collection,
                payload={"tags": new_tags},
                points=[point_id],
            )
            logger.info(f"移除标签成功: {point_id} -> 移除 {tags}")
            return True
        except Exception as e:
            logger.error(f"移除标签失败: {e}")
            return False
    
    def set_tags(self, point_id: str, tags: List[str]) -> bool:
        """设置记忆条目的标签（覆盖）"""
        try:
            self.qdrant.set_payload(
                collection_name=self.collection,
                payload={"tags": list(set(tags))},
                points=[point_id],
            )
            logger.info(f"设置标签成功: {point_id} -> {tags}")
            return True
        except Exception as e:
            logger.error(f"设置标签失败: {e}")
            return False
    
    def get_tags(self, point_id: str) -> List[str]:
        """获取记忆条目的标签"""
        try:
            result = self.qdrant.retrieve(
                collection_name=self.collection,
                ids=[point_id],
                with_payload=True,
            )
            if result:
                return result[0].payload.get("tags", [])
        except Exception as e:
            logger.error(f"获取标签失败: {e}")
        return []
    
    # ============ 按标签搜索 ============
    
    def search_by_tags(
        self,
        tags: List[str],
        match_all: bool = False,
        limit: int = 50,
    ) -> List[TaggedMemory]:
        """
        按标签搜索记忆
        
        Args:
            tags: 标签列表
            match_all: True=必须包含所有标签, False=包含任一标签
            limit: 返回数量上限
        """
        try:
            if match_all:
                # 所有标签都必须匹配
                must_conditions = [
                    FieldCondition(
                        key="tags",
                        match=MatchValue(value=tag),
                    )
                    for tag in tags
                ]
                query_filter = Filter(must=must_conditions)
            else:
                # 匹配任一标签
                should_conditions = [
                    FieldCondition(
                        key="tags",
                        match=MatchValue(value=tag),
                    )
                    for tag in tags
                ]
                query_filter = Filter(should=should_conditions)
            
            results = self.qdrant.scroll(
                collection_name=self.collection,
                scroll_filter=query_filter,
                limit=limit,
                with_payload=True,
            )
            
            memories = []
            for point in results[0]:
                memories.append(TaggedMemory(
                    id=str(point.id),
                    text=point.payload.get("text", ""),
                    file_name=point.payload.get("file_name", ""),
                    tags=point.payload.get("tags", []),
                ))
            
            return memories
        except Exception as e:
            logger.error(f"按标签搜索失败: {e}")
            return []
    
    def list_all_tags(self) -> List[str]:
        """列出所有已使用的标签"""
        try:
            all_tags = set()
            offset = None
            while True:
                results, next_offset = self.qdrant.scroll(
                    collection_name=self.collection,
                    limit=100,
                    offset=offset,
                    with_payload=True,
                )
                for point in results:
                    tags = point.payload.get("tags", [])
                    all_tags.update(tags)
                
                if next_offset is None:
                    break
                offset = next_offset
            
            return sorted(list(all_tags))
        except Exception as e:
            logger.error(f"列出标签失败: {e}")
            return []
    
    def delete_by_tag(self, tag: str) -> int:
        """删除带有指定标签的所有记忆（返回删除数量）"""
        try:
            result = self.qdrant.delete(
                collection_name=self.collection,
                points_selector=Filter(
                    must=[FieldCondition(key="tags", match=MatchValue(value=tag))]
                ),
            )
            logger.info(f"删除标签 '{tag}' 的记忆: {result}")
            return result
        except Exception as e:
            logger.error(f"删除标签记忆失败: {e}")
            return 0


# 快捷函数
def get_tag_manager() -> MemoryTagManager:
    return MemoryTagManager()


if __name__ == "__main__":
    mgr = MemoryTagManager()
    print(f"所有标签: {mgr.list_all_tags()}")
