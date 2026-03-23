"""
基于RAG的安全知识检索系统

利用现有的RAG模块实现安全知识的向量检索
"""

import logging
from typing import List, Dict, Any, Optional

from .base import KnowledgeDocument, KnowledgeCategory

logger = logging.getLogger(__name__)


class SecurityKnowledgeRAG:
    """
    安全知识RAG检索系统
    
    使用现有的RAG模块进行向量检索
    """
    
    COLLECTION_NAME = "security_knowledge"
    
    def __init__(
        self,
        persist_directory: Optional[str] = None,
    ):
        self.persist_directory = persist_directory
        self._indexer = None
        self._retriever = None
        self._initialized = False
        
        # 内置知识库 - 从模块化文件加载
        self._builtin_knowledge = self._load_builtin_knowledge()
    
    async def initialize(self):
        """初始化RAG组件"""
        if self._initialized:
            return
        
        try:
            from ...rag import CodeIndexer, CodeRetriever, EmbeddingService
            
            embedding_service = EmbeddingService()
            
            self._indexer = CodeIndexer(
                collection_name=self.COLLECTION_NAME,
                embedding_service=embedding_service,
                persist_directory=self.persist_directory,
            )
            
            self._retriever = CodeRetriever(
                collection_name=self.COLLECTION_NAME,
                embedding_service=embedding_service,
                persist_directory=self.persist_directory,
            )
            
            await self._indexer.initialize()
            await self._retriever.initialize()
            
            # 检查是否需要索引内置知识
            count = await self._indexer.get_chunk_count()
            if count == 0:
                await self._index_builtin_knowledge()
            
            self._initialized = True
            logger.info("SecurityKnowledgeRAG initialized")
            
        except Exception as e:
            logger.warning(f"Failed to initialize RAG: {e}, using fallback")
            self._initialized = True  # 标记为已初始化，使用fallback
    
    def _load_builtin_knowledge(self) -> List[KnowledgeDocument]:
        """从模块化文件加载内置安全知识"""
        all_docs = []
        
        # 加载Web3漏洞知识
        try:
            from .vulnerabilities import ALL_VULNERABILITY_DOCS
            all_docs.extend(ALL_VULNERABILITY_DOCS)
            logger.debug(f"Loaded {len(ALL_VULNERABILITY_DOCS)} vulnerability docs")
        except ImportError as e:
            logger.warning(f"Failed to load vulnerability docs: {e}")
        
        # 加载框架知识
        try:
            from .frameworks import ALL_FRAMEWORK_DOCS
            all_docs.extend(ALL_FRAMEWORK_DOCS)
            logger.debug(f"Loaded {len(ALL_FRAMEWORK_DOCS)} framework docs")
        except ImportError as e:
            logger.warning(f"Failed to load framework docs: {e}")
        
        logger.info(f"Total knowledge documents loaded: {len(all_docs)}")
        return all_docs
    
    async def _index_builtin_knowledge(self):
        """索引内置知识到向量数据库"""
        if not self._indexer:
            return
        
        logger.info("Indexing builtin security knowledge...")
        
        # 转换为RAG可索引的格式
        files = []
        for doc in self._builtin_knowledge:
            files.append({
                "path": f"knowledge/{doc.category.value}/{doc.id}.md",
                "content": doc.to_embedding_text(),
            })
        
        async for progress in self._indexer.index_files(files, base_path="knowledge"):
            pass
        
        logger.info(f"Indexed {len(files)} knowledge documents")
    
    async def search(
        self,
        query: str,
        category: Optional[KnowledgeCategory] = None,
        top_k: int = 5,
    ) -> List[Dict[str, Any]]:
        """
        搜索安全知识
        
        Args:
            query: 搜索查询
            category: 知识类别过滤
            top_k: 返回数量
            
        Returns:
            匹配的知识文档列表
        """
        await self.initialize()
        
        # 如果RAG可用，使用向量检索
        if self._retriever:
            try:
                results = await self._retriever.retrieve(
                    query=query,
                    top_k=top_k,
                )
                
                return [
                    {
                        "id": r.chunk_id,
                        "content": r.content,
                        "score": r.score,
                        "file_path": r.file_path,
                    }
                    for r in results
                ]
            except Exception as e:
                logger.warning(f"RAG search failed: {e}, using fallback")
        
        # Fallback: 简单关键词匹配
        return self._fallback_search(query, category, top_k)
    
    def _fallback_search(
        self,
        query: str,
        category: Optional[KnowledgeCategory],
        top_k: int,
    ) -> List[Dict[str, Any]]:
        """简单的关键词匹配搜索（fallback）"""
        query_lower = query.lower()
        query_terms = query_lower.split()
        results = []
        
        for doc in self._builtin_knowledge:
            if category and doc.category != category:
                continue
            
            # 计算匹配分数
            score = 0
            content_lower = doc.content.lower()
            title_lower = doc.title.lower()
            
            # 标题匹配权重更高
            for term in query_terms:
                if term in title_lower:
                    score += 0.3
                if term in content_lower:
                    score += 0.1
            
            # 完整查询匹配
            if query_lower in title_lower:
                score += 0.5
            if query_lower in content_lower:
                score += 0.2
            
            # 标签匹配
            for tag in doc.tags:
                if query_lower in tag.lower() or any(t in tag.lower() for t in query_terms):
                    score += 0.15
            
            # CWE/OWASP匹配
            for cwe in doc.cwe_ids:
                if query_lower in cwe.lower():
                    score += 0.25
            for owasp in doc.owasp_ids:
                if query_lower in owasp.lower():
                    score += 0.25
            
            if score > 0:
                results.append({
                    "id": doc.id,
                    "title": doc.title,
                    "content": doc.content,
                    "category": doc.category.value,
                    "score": min(score, 1.0),
                    "tags": doc.tags,
                    "cwe_ids": doc.cwe_ids,
                    "severity": doc.severity,
                })
        
        # 按分数排序
        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:top_k]
    
    async def get_vulnerability_knowledge(
        self,
        vuln_type: str,
    ) -> Optional[Dict[str, Any]]:
        """
        获取特定漏洞类型的知识
        
        Args:
            vuln_type: 漏洞类型（如Flash Loan, DoS等）
            
        Returns:
            漏洞知识文档
        """
        # 标准化漏洞类型名称
        vuln_type_normalized = vuln_type.lower().replace("-", "_").replace(" ", "_")
        
        # 先尝试精确匹配
        for doc in self._builtin_knowledge:
            if doc.id == f"vuln_{vuln_type_normalized}" or doc.id == vuln_type_normalized:
                return doc.to_dict()
        
        # 尝试部分匹配
        for doc in self._builtin_knowledge:
            if vuln_type_normalized in doc.id:
                return doc.to_dict()
        
        # 使用搜索
        results = await self.search(vuln_type, top_k=1)
        return results[0] if results else None
    
    async def get_framework_knowledge(
        self,
        framework: str,
    ) -> Optional[Dict[str, Any]]:
        """
        获取特定框架的安全知识
        
        Args:
            framework: 框架名称（如fastapi, django等）
            
        Returns:
            框架安全知识文档
        """
        framework_normalized = framework.lower().replace("-", "_").replace(" ", "_")
        
        for doc in self._builtin_knowledge:
            if doc.category == KnowledgeCategory.FRAMEWORK:
                if doc.id == f"framework_{framework_normalized}" or framework_normalized in doc.id:
                    return doc.to_dict()
        
        # 使用搜索
        results = await self.search(framework, category=KnowledgeCategory.FRAMEWORK, top_k=1)
        return results[0] if results else None
    
    def get_all_vulnerability_types(self) -> List[str]:
        """获取所有支持的漏洞类型"""
        return [
            doc.id.replace("vuln_", "")
            for doc in self._builtin_knowledge
            if doc.category == KnowledgeCategory.VULNERABILITY
        ]
    
    def get_all_frameworks(self) -> List[str]:
        """获取所有支持的框架"""
        return [
            doc.id.replace("framework_", "")
            for doc in self._builtin_knowledge
            if doc.category == KnowledgeCategory.FRAMEWORK
        ]
    
    def get_knowledge_by_tags(self, tags: List[str]) -> List[Dict[str, Any]]:
        """根据标签获取知识"""
        results = []
        tags_lower = [t.lower() for t in tags]
        
        for doc in self._builtin_knowledge:
            doc_tags_lower = [t.lower() for t in doc.tags]
            if any(tag in doc_tags_lower for tag in tags_lower):
                results.append(doc.to_dict())
        
        return results
    
    def get_knowledge_stats(self) -> Dict[str, Any]:
        """获取知识库统计信息"""
        stats = {
            "total": len(self._builtin_knowledge),
            "by_category": {},
            "by_severity": {},
        }
        
        for doc in self._builtin_knowledge:
            cat = doc.category.value
            stats["by_category"][cat] = stats["by_category"].get(cat, 0) + 1
            
            if doc.severity:
                sev = doc.severity
                stats["by_severity"][sev] = stats["by_severity"].get(sev, 0) + 1
        
        return stats


# 全局实例
security_knowledge_rag = SecurityKnowledgeRAG()
