"""
代码索引器
将代码分块并索引到向量数据库

🔥 v2.0 改进：
- 支持嵌入模型变更检测和自动重建
- 支持增量索引更新（基于文件 hash）
- 支持索引版本控制和状态查询
"""

import os
import asyncio
import logging
import hashlib
import time
from typing import List, Dict, Any, Optional, AsyncGenerator, Callable, Set, Tuple
from pathlib import Path
from dataclasses import dataclass, field
from enum import Enum
import json

from .splitter import CodeSplitter, CodeChunk
from .embeddings import EmbeddingService

logger = logging.getLogger(__name__)

# 索引版本号（当索引格式变化时递增）
INDEX_VERSION = "2.0"


# 支持的文本文件扩展名
TEXT_EXTENSIONS = {
    ".py", ".js", ".ts", ".tsx", ".jsx", ".java", ".go", ".rs",
    ".cpp", ".c", ".h", ".cc", ".hh", ".cs", ".php", ".rb",
    ".kt", ".swift", ".sql", ".sh", ".json", ".yml", ".yaml",
    ".xml", ".html", ".css", ".vue", ".svelte", ".md",
}

# 排除的目录
EXCLUDE_DIRS = {
    "node_modules", "vendor", "dist", "build", ".git",
    "__pycache__", ".pytest_cache", "coverage", ".nyc_output",
    ".vscode", ".idea", ".vs", "target", "out", "bin", "obj",
    "__MACOSX", ".next", ".nuxt", "venv", "env", ".env",
}

# 排除的文件
EXCLUDE_FILES = {
    ".DS_Store", "package-lock.json", "yarn.lock", "pnpm-lock.yaml",
    "Cargo.lock", "poetry.lock", "composer.lock", "Gemfile.lock",
}


class IndexUpdateMode(Enum):
    """索引更新模式"""
    FULL = "full"           # 全量重建：删除旧索引，完全重新索引
    INCREMENTAL = "incremental"  # 增量更新：只更新变化的文件
    SMART = "smart"         # 智能模式：根据情况自动选择


@dataclass
class IndexStatus:
    """索引状态信息"""
    collection_name: str
    exists: bool = False
    index_version: str = ""
    chunk_count: int = 0
    file_count: int = 0
    created_at: float = 0.0
    updated_at: float = 0.0
    embedding_provider: str = ""
    embedding_model: str = ""
    embedding_dimension: int = 0
    project_hash: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "collection_name": self.collection_name,
            "exists": self.exists,
            "index_version": self.index_version,
            "chunk_count": self.chunk_count,
            "file_count": self.file_count,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "embedding_provider": self.embedding_provider,
            "embedding_model": self.embedding_model,
            "embedding_dimension": self.embedding_dimension,
            "project_hash": self.project_hash,
        }


@dataclass
class IndexingProgress:
    """索引进度"""
    total_files: int = 0
    processed_files: int = 0
    total_chunks: int = 0
    indexed_chunks: int = 0
    current_file: str = ""
    errors: List[str] = None
    # 🔥 新增：增量更新统计
    added_files: int = 0
    updated_files: int = 0
    deleted_files: int = 0
    skipped_files: int = 0
    update_mode: str = "full"
    # 🔥 新增：状态消息（用于前端显示）
    status_message: str = ""

    def __post_init__(self):
        if self.errors is None:
            self.errors = []

    @property
    def progress_percentage(self) -> float:
        if self.total_files == 0:
            return 0.0
        return (self.processed_files / self.total_files) * 100


@dataclass
class IndexingResult:
    """索引结果"""
    success: bool
    total_files: int
    indexed_files: int
    total_chunks: int
    errors: List[str]
    collection_name: str


class VectorStore:
    """向量存储抽象基类"""

    async def initialize(self):
        """初始化存储"""
        pass

    async def add_documents(
        self,
        ids: List[str],
        embeddings: List[List[float]],
        documents: List[str],
        metadatas: List[Dict[str, Any]],
    ):
        """添加文档"""
        raise NotImplementedError

    async def upsert_documents(
        self,
        ids: List[str],
        embeddings: List[List[float]],
        documents: List[str],
        metadatas: List[Dict[str, Any]],
    ):
        """更新或插入文档"""
        raise NotImplementedError

    async def delete_by_file_path(self, file_path: str) -> int:
        """删除指定文件的所有文档，返回删除数量"""
        raise NotImplementedError

    async def delete_by_ids(self, ids: List[str]) -> int:
        """删除指定 ID 的文档"""
        raise NotImplementedError

    async def query(
        self,
        query_embedding: List[float],
        n_results: int = 10,
        where: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """查询"""
        raise NotImplementedError

    async def delete_collection(self):
        """删除集合"""
        raise NotImplementedError

    async def get_count(self) -> int:
        """获取文档数量"""
        raise NotImplementedError

    async def get_all_file_paths(self) -> Set[str]:
        """获取所有已索引的文件路径"""
        raise NotImplementedError

    async def get_file_hashes(self) -> Dict[str, str]:
        """获取所有文件的 hash 映射 {file_path: hash}"""
        raise NotImplementedError

    def get_collection_metadata(self) -> Dict[str, Any]:
        """获取 collection 元数据"""
        raise NotImplementedError


class ChromaVectorStore(VectorStore):
    """
    Chroma 向量存储

    🔥 v2.0 改进：
    - 支持 embedding 配置变更检测
    - 支持增量更新（upsert、delete）
    - 支持文件级别的索引管理
    """

    def __init__(
        self,
        collection_name: str,
        persist_directory: Optional[str] = None,
        embedding_config: Optional[Dict[str, Any]] = None,
    ):
        self.collection_name = collection_name
        self.persist_directory = persist_directory
        self.embedding_config = embedding_config or {}
        self._client = None
        self._collection = None
        self._is_new_collection = False

    async def initialize(self, force_recreate: bool = False):
        """
        初始化 Chroma

        Args:
            force_recreate: 是否强制重建 collection
        """
        try:
            import chromadb
            from chromadb.config import Settings

            if self.persist_directory:
                self._client = chromadb.PersistentClient(
                    path=self.persist_directory,
                    settings=Settings(anonymized_telemetry=False),
                )
            else:
                self._client = chromadb.Client(
                    settings=Settings(anonymized_telemetry=False),
                )

            # 检查 collection 是否存在
            existing_collections = [c.name for c in self._client.list_collections()]
            collection_exists = self.collection_name in existing_collections

            # 如果需要强制重建，先删除
            if force_recreate and collection_exists:
                logger.info(f"🗑️ 强制重建: 删除旧 collection '{self.collection_name}'")
                self._client.delete_collection(name=self.collection_name)
                collection_exists = False

            # 构建 collection 元数据
            current_time = time.time()
            collection_metadata = {
                "hnsw:space": "cosine",
                "index_version": INDEX_VERSION,
            }

            if self.embedding_config:
                collection_metadata["embedding_provider"] = self.embedding_config.get("provider", "openai")
                collection_metadata["embedding_model"] = self.embedding_config.get("model", "text-embedding-3-small")
                collection_metadata["embedding_dimension"] = self.embedding_config.get("dimension", 1536)
                if self.embedding_config.get("base_url"):
                    collection_metadata["embedding_base_url"] = self.embedding_config.get("base_url")

            if collection_exists:
                # 获取现有 collection
                self._collection = self._client.get_collection(name=self.collection_name)
                self._is_new_collection = False
                logger.info(f"📂 获取现有 collection '{self.collection_name}'")
            else:
                # 创建新 collection
                collection_metadata["created_at"] = current_time
                collection_metadata["updated_at"] = current_time
                self._collection = self._client.create_collection(
                    name=self.collection_name,
                    metadata=collection_metadata,
                )
                self._is_new_collection = True
                logger.info(f"✨ 创建新 collection '{self.collection_name}'")

        except ImportError:
            raise ImportError("chromadb is required. Install with: pip install chromadb")

    @property
    def is_new_collection(self) -> bool:
        """是否是新创建的 collection"""
        return self._is_new_collection

    def get_embedding_config(self) -> Dict[str, Any]:
        """获取 collection 的 embedding 配置"""
        if not self._collection:
            return {}

        metadata = self._collection.metadata or {}
        return {
            "provider": metadata.get("embedding_provider"),
            "model": metadata.get("embedding_model"),
            "dimension": metadata.get("embedding_dimension"),
            "base_url": metadata.get("embedding_base_url"),
        }

    def get_collection_metadata(self) -> Dict[str, Any]:
        """获取 collection 完整元数据"""
        if not self._collection:
            return {}
        return dict(self._collection.metadata or {})

    def _clean_metadatas(self, metadatas: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """清理元数据，确保符合 Chroma 要求"""
        cleaned_metadatas = []
        for meta in metadatas:
            cleaned = {}
            for k, v in meta.items():
                if isinstance(v, (str, int, float, bool)):
                    cleaned[k] = v
                elif isinstance(v, list):
                    cleaned[k] = json.dumps(v)
                elif v is not None:
                    cleaned[k] = str(v)
            cleaned_metadatas.append(cleaned)
        return cleaned_metadatas

    async def add_documents(
        self,
        ids: List[str],
        embeddings: List[List[float]],
        documents: List[str],
        metadatas: List[Dict[str, Any]],
    ):
        """添加文档到 Chroma"""
        if not ids:
            return

        cleaned_metadatas = self._clean_metadatas(metadatas)

        # 分批添加（Chroma 批次限制）
        batch_size = 500
        for i in range(0, len(ids), batch_size):
            batch_ids = ids[i:i + batch_size]
            batch_embeddings = embeddings[i:i + batch_size]
            batch_documents = documents[i:i + batch_size]
            batch_metadatas = cleaned_metadatas[i:i + batch_size]

            await asyncio.to_thread(
                self._collection.add,
                ids=batch_ids,
                embeddings=batch_embeddings,
                documents=batch_documents,
                metadatas=batch_metadatas,
            )

    async def upsert_documents(
        self,
        ids: List[str],
        embeddings: List[List[float]],
        documents: List[str],
        metadatas: List[Dict[str, Any]],
    ):
        """更新或插入文档（用于增量更新）"""
        if not ids:
            return

        cleaned_metadatas = self._clean_metadatas(metadatas)

        # 分批 upsert
        batch_size = 500
        for i in range(0, len(ids), batch_size):
            batch_ids = ids[i:i + batch_size]
            batch_embeddings = embeddings[i:i + batch_size]
            batch_documents = documents[i:i + batch_size]
            batch_metadatas = cleaned_metadatas[i:i + batch_size]

            await asyncio.to_thread(
                self._collection.upsert,
                ids=batch_ids,
                embeddings=batch_embeddings,
                documents=batch_documents,
                metadatas=batch_metadatas,
            )

    async def delete_by_file_path(self, file_path: str) -> int:
        """删除指定文件的所有文档"""
        if not self._collection:
            return 0

        try:
            # 查询该文件的所有文档
            result = await asyncio.to_thread(
                self._collection.get,
                where={"file_path": file_path},
            )

            ids_to_delete = result.get("ids", [])
            if ids_to_delete:
                await asyncio.to_thread(
                    self._collection.delete,
                    ids=ids_to_delete,
                )
                logger.debug(f"删除文件 '{file_path}' 的 {len(ids_to_delete)} 个文档")

            return len(ids_to_delete)
        except Exception as e:
            logger.warning(f"删除文件文档失败: {e}")
            return 0

    async def delete_by_ids(self, ids: List[str]) -> int:
        """删除指定 ID 的文档"""
        if not self._collection or not ids:
            return 0

        try:
            await asyncio.to_thread(
                self._collection.delete,
                ids=ids,
            )
            return len(ids)
        except Exception as e:
            logger.warning(f"删除文档失败: {e}")
            return 0

    async def query(
        self,
        query_embedding: List[float],
        n_results: int = 10,
        where: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """查询 Chroma"""
        result = await asyncio.to_thread(
            self._collection.query,
            query_embeddings=[query_embedding],
            n_results=n_results,
            where=where,
            include=["documents", "metadatas", "distances"],
        )

        return {
            "ids": result["ids"][0] if result["ids"] else [],
            "documents": result["documents"][0] if result["documents"] else [],
            "metadatas": result["metadatas"][0] if result["metadatas"] else [],
            "distances": result["distances"][0] if result["distances"] else [],
        }

    async def delete_collection(self):
        """删除集合"""
        if self._client and self._collection:
            await asyncio.to_thread(
                self._client.delete_collection,
                name=self.collection_name,
            )
            self._collection = None

    async def get_count(self) -> int:
        """获取文档数量"""
        if self._collection:
            return await asyncio.to_thread(self._collection.count)
        return 0

    async def get_all_file_paths(self) -> Set[str]:
        """获取所有已索引的文件路径"""
        if not self._collection:
            return set()

        try:
            # 获取所有文档的元数据
            result = await asyncio.to_thread(
                self._collection.get,
                include=["metadatas"],
            )

            file_paths = set()
            for meta in result.get("metadatas", []):
                if meta and "file_path" in meta:
                    file_paths.add(meta["file_path"])

            return file_paths
        except Exception as e:
            logger.warning(f"获取文件路径失败: {e}")
            return set()

    async def get_file_hashes(self) -> Dict[str, str]:
        """获取所有文件的 hash 映射 {file_path: file_hash}"""
        if not self._collection:
            return {}

        try:
            result = await asyncio.to_thread(
                self._collection.get,
                include=["metadatas"],
            )

            file_hashes = {}
            for meta in result.get("metadatas", []):
                if meta:
                    file_path = meta.get("file_path")
                    file_hash = meta.get("file_hash")
                    if file_path and file_hash:
                        # 同一文件可能有多个 chunk，hash 应该相同
                        file_hashes[file_path] = file_hash

            return file_hashes
        except Exception as e:
            logger.warning(f"获取文件 hash 失败: {e}")
            return {}

    async def update_collection_metadata(self, updates: Dict[str, Any]):
        """更新 collection 元数据"""
        if not self._collection:
            return

        try:
            current_metadata = dict(self._collection.metadata or {})
            current_metadata.update(updates)
            current_metadata["updated_at"] = time.time()

            # Chroma 不支持直接更新元数据，需要通过修改 collection
            # 这里我们使用 modify 方法
            await asyncio.to_thread(
                self._collection.modify,
                metadata=current_metadata,
            )
        except Exception as e:
            logger.warning(f"更新 collection 元数据失败: {e}")


class InMemoryVectorStore(VectorStore):
    """内存向量存储（用于测试或小项目）"""

    def __init__(self, collection_name: str, embedding_config: Optional[Dict[str, Any]] = None):
        self.collection_name = collection_name
        self.embedding_config = embedding_config or {}
        self._documents: Dict[str, Dict[str, Any]] = {}
        self._metadata: Dict[str, Any] = {
            "created_at": time.time(),
            "index_version": INDEX_VERSION,
        }
        self._is_new_collection = True

    async def initialize(self, force_recreate: bool = False):
        """初始化"""
        if force_recreate:
            self._documents.clear()
            self._is_new_collection = True
        logger.info(f"InMemory vector store '{self.collection_name}' initialized")

    @property
    def is_new_collection(self) -> bool:
        return self._is_new_collection

    def get_embedding_config(self) -> Dict[str, Any]:
        return self.embedding_config

    def get_collection_metadata(self) -> Dict[str, Any]:
        return self._metadata

    async def add_documents(
        self,
        ids: List[str],
        embeddings: List[List[float]],
        documents: List[str],
        metadatas: List[Dict[str, Any]],
    ):
        """添加文档"""
        for id_, emb, doc, meta in zip(ids, embeddings, documents, metadatas):
            self._documents[id_] = {
                "embedding": emb,
                "document": doc,
                "metadata": meta,
            }
        self._is_new_collection = False

    async def upsert_documents(
        self,
        ids: List[str],
        embeddings: List[List[float]],
        documents: List[str],
        metadatas: List[Dict[str, Any]],
    ):
        """更新或插入文档"""
        await self.add_documents(ids, embeddings, documents, metadatas)

    async def delete_by_file_path(self, file_path: str) -> int:
        """删除指定文件的所有文档"""
        ids_to_delete = [
            id_ for id_, data in self._documents.items()
            if data["metadata"].get("file_path") == file_path
        ]
        for id_ in ids_to_delete:
            del self._documents[id_]
        return len(ids_to_delete)

    async def delete_by_ids(self, ids: List[str]) -> int:
        """删除指定 ID 的文档"""
        count = 0
        for id_ in ids:
            if id_ in self._documents:
                del self._documents[id_]
                count += 1
        return count

    async def query(
        self,
        query_embedding: List[float],
        n_results: int = 10,
        where: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """查询（使用余弦相似度）"""
        import math

        def cosine_similarity(a: List[float], b: List[float]) -> float:
            dot = sum(x * y for x, y in zip(a, b))
            norm_a = math.sqrt(sum(x * x for x in a))
            norm_b = math.sqrt(sum(x * x for x in b))
            if norm_a == 0 or norm_b == 0:
                return 0.0
            return dot / (norm_a * norm_b)

        results = []
        for id_, data in self._documents.items():
            # 应用过滤条件
            if where:
                match = True
                for k, v in where.items():
                    if data["metadata"].get(k) != v:
                        match = False
                        break
                if not match:
                    continue

            similarity = cosine_similarity(query_embedding, data["embedding"])
            results.append({
                "id": id_,
                "document": data["document"],
                "metadata": data["metadata"],
                "distance": 1 - similarity,
            })

        results.sort(key=lambda x: x["distance"])
        results = results[:n_results]

        return {
            "ids": [r["id"] for r in results],
            "documents": [r["document"] for r in results],
            "metadatas": [r["metadata"] for r in results],
            "distances": [r["distance"] for r in results],
        }

    async def delete_collection(self):
        """删除集合"""
        self._documents.clear()

    async def get_count(self) -> int:
        """获取文档数量"""
        return len(self._documents)

    async def get_all_file_paths(self) -> Set[str]:
        """获取所有已索引的文件路径"""
        return {
            data["metadata"].get("file_path")
            for data in self._documents.values()
            if data["metadata"].get("file_path")
        }

    async def get_file_hashes(self) -> Dict[str, str]:
        """获取所有文件的 hash 映射"""
        file_hashes = {}
        for data in self._documents.values():
            file_path = data["metadata"].get("file_path")
            file_hash = data["metadata"].get("file_hash")
            if file_path and file_hash:
                file_hashes[file_path] = file_hash
        return file_hashes

    async def update_collection_metadata(self, updates: Dict[str, Any]):
        """更新 collection 元数据"""
        self._metadata.update(updates)
        self._metadata["updated_at"] = time.time()


class CodeIndexer:
    """
    代码索引器
    将代码文件分块、嵌入并索引到向量数据库

    🔥 v2.0 改进：
    - 自动检测 embedding 模型变更并重建索引
    - 支持增量索引更新（基于文件 hash）
    - 支持索引状态查询
    """

    def __init__(
        self,
        collection_name: str,
        embedding_service: Optional[EmbeddingService] = None,
        vector_store: Optional[VectorStore] = None,
        splitter: Optional[CodeSplitter] = None,
        persist_directory: Optional[str] = None,
    ):
        """
        初始化索引器

        Args:
            collection_name: 向量集合名称
            embedding_service: 嵌入服务
            vector_store: 向量存储
            splitter: 代码分块器
            persist_directory: 持久化目录
        """
        self.collection_name = collection_name
        self.embedding_service = embedding_service or EmbeddingService()
        self.splitter = splitter or CodeSplitter()
        self.persist_directory = persist_directory

        # 从 embedding_service 获取配置
        self.embedding_config = {
            "provider": getattr(self.embedding_service, 'provider', 'openai'),
            "model": getattr(self.embedding_service, 'model', 'text-embedding-3-small'),
            "dimension": getattr(self.embedding_service, 'dimension', 1536),
            "base_url": getattr(self.embedding_service, 'base_url', None),
        }

        # 创建向量存储
        if vector_store:
            self.vector_store = vector_store
        else:
            try:
                self.vector_store = ChromaVectorStore(
                    collection_name=collection_name,
                    persist_directory=persist_directory,
                    embedding_config=self.embedding_config,
                )
            except ImportError:
                logger.warning("Chroma not available, using in-memory store")
                self.vector_store = InMemoryVectorStore(
                    collection_name=collection_name,
                    embedding_config=self.embedding_config,
                )

        self._initialized = False
        self._needs_rebuild = False
        self._rebuild_reason = ""

    @staticmethod
    def _read_file_sync(file_path: str) -> str:
        """
        同步读取文件内容（用于 asyncio.to_thread 包装）

        Args:
            file_path: 文件路径

        Returns:
            文件内容
        """
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            return f.read()

    async def initialize(self, force_rebuild: bool = False) -> Tuple[bool, str]:
        """
        初始化索引器，检测是否需要重建索引

        Args:
            force_rebuild: 是否强制重建

        Returns:
            (needs_rebuild, reason) - 是否需要重建及原因
        """
        if self._initialized and not force_rebuild:
            return self._needs_rebuild, self._rebuild_reason

        # 先初始化 vector_store（不强制重建，只是获取现有 collection）
        await self.vector_store.initialize(force_recreate=False)

        # 检查是否需要重建
        self._needs_rebuild, self._rebuild_reason = await self._check_rebuild_needed()

        if force_rebuild:
            self._needs_rebuild = True
            self._rebuild_reason = "用户强制重建"

        # 如果需要重建，重新初始化 vector_store（强制重建）
        if self._needs_rebuild:
            logger.info(f"🔄 需要重建索引: {self._rebuild_reason}")
            await self.vector_store.initialize(force_recreate=True)

        self._initialized = True
        return self._needs_rebuild, self._rebuild_reason

    async def _check_rebuild_needed(self) -> Tuple[bool, str]:
        """
        检查是否需要重建索引

        Returns:
            (needs_rebuild, reason)
        """
        # 如果是新 collection，不需要重建（因为本来就是空的）
        if hasattr(self.vector_store, 'is_new_collection') and self.vector_store.is_new_collection:
            return False, ""

        # 获取现有 collection 的配置
        stored_config = self.vector_store.get_embedding_config()
        stored_metadata = self.vector_store.get_collection_metadata()

        # 检查索引版本
        stored_version = stored_metadata.get("index_version", "1.0")
        if stored_version != INDEX_VERSION:
            return True, f"索引版本变更: {stored_version} -> {INDEX_VERSION}"

        # 检查 embedding 提供商
        stored_provider = stored_config.get("provider")
        current_provider = self.embedding_config.get("provider")
        if stored_provider and current_provider and stored_provider != current_provider:
            return True, f"Embedding 提供商变更: {stored_provider} -> {current_provider}"

        # 检查 embedding 模型
        stored_model = stored_config.get("model")
        current_model = self.embedding_config.get("model")
        if stored_model and current_model and stored_model != current_model:
            return True, f"Embedding 模型变更: {stored_model} -> {current_model}"

        # 检查维度
        stored_dimension = stored_config.get("dimension")
        current_dimension = self.embedding_config.get("dimension")
        if stored_dimension and current_dimension and stored_dimension != current_dimension:
            return True, f"Embedding 维度变更: {stored_dimension} -> {current_dimension}"

        return False, ""

    async def get_index_status(self) -> IndexStatus:
        """获取索引状态"""
        await self.initialize()

        metadata = self.vector_store.get_collection_metadata()
        embedding_config = self.vector_store.get_embedding_config()
        chunk_count = await self.vector_store.get_count()
        file_paths = await self.vector_store.get_all_file_paths()

        return IndexStatus(
            collection_name=self.collection_name,
            exists=chunk_count > 0,
            index_version=metadata.get("index_version", ""),
            chunk_count=chunk_count,
            file_count=len(file_paths),
            created_at=metadata.get("created_at", 0),
            updated_at=metadata.get("updated_at", 0),
            embedding_provider=embedding_config.get("provider", ""),
            embedding_model=embedding_config.get("model", ""),
            embedding_dimension=embedding_config.get("dimension", 0),
            project_hash=metadata.get("project_hash", ""),
        )

    async def smart_index_directory(
        self,
        directory: str,
        exclude_patterns: Optional[List[str]] = None,
        include_patterns: Optional[List[str]] = None,
        update_mode: IndexUpdateMode = IndexUpdateMode.SMART,
        progress_callback: Optional[Callable[[IndexingProgress], None]] = None,
        embedding_progress_callback: Optional[Callable[[int, int], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> AsyncGenerator[IndexingProgress, None]:
        """
        智能索引目录

        Args:
            directory: 目录路径
            exclude_patterns: 排除模式
            include_patterns: 包含模式（🔥 用于限制只索引指定文件）
            update_mode: 更新模式
            progress_callback: 进度回调
            embedding_progress_callback: 嵌入进度回调，接收 (processed, total) 参数
            cancel_check: 取消检查函数，返回 True 表示应该取消

        Yields:
            索引进度
        """
        # 初始化并检查是否需要重建
        needs_rebuild, rebuild_reason = await self.initialize()

        progress = IndexingProgress()
        exclude_patterns = exclude_patterns or []

        # 确定实际的更新模式
        if update_mode == IndexUpdateMode.SMART:
            if needs_rebuild:
                actual_mode = IndexUpdateMode.FULL
                logger.info(f"🔄 智能模式: 选择全量重建 (原因: {rebuild_reason})")
            else:
                actual_mode = IndexUpdateMode.INCREMENTAL
                logger.info("📝 智能模式: 选择增量更新")
        else:
            actual_mode = update_mode

        progress.update_mode = actual_mode.value

        if actual_mode == IndexUpdateMode.FULL:
            # 全量重建
            async for p in self._full_index(directory, exclude_patterns, include_patterns, progress, progress_callback, embedding_progress_callback, cancel_check):
                yield p
        else:
            # 增量更新
            async for p in self._incremental_index(directory, exclude_patterns, include_patterns, progress, progress_callback, embedding_progress_callback, cancel_check):
                yield p

    async def _full_index(
        self,
        directory: str,
        exclude_patterns: List[str],
        include_patterns: Optional[List[str]],
        progress: IndexingProgress,
        progress_callback: Optional[Callable[[IndexingProgress], None]],
        embedding_progress_callback: Optional[Callable[[int, int], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> AsyncGenerator[IndexingProgress, None]:
        """全量索引"""
        logger.info("🔄 开始全量索引...")

        # 收集文件
        files = self._collect_files(directory, exclude_patterns, include_patterns)
        progress.total_files = len(files)

        logger.info(f"📁 发现 {len(files)} 个文件待索引")
        yield progress

        all_chunks: List[CodeChunk] = []
        file_hashes: Dict[str, str] = {}

        # 分块处理文件
        for file_path in files:
            progress.current_file = file_path

            try:
                relative_path = os.path.relpath(file_path, directory)

                # 异步读取文件，避免阻塞事件循环
                content = await asyncio.to_thread(
                    self._read_file_sync, file_path
                )

                if not content.strip():
                    progress.processed_files += 1
                    progress.skipped_files += 1
                    continue

                # 计算文件 hash
                file_hash = hashlib.md5(content.encode()).hexdigest()
                file_hashes[relative_path] = file_hash

                # 限制文件大小
                if len(content) > 500000:
                    content = content[:500000]

                # 异步分块，避免 Tree-sitter 解析阻塞事件循环
                chunks = await self.splitter.split_file_async(content, relative_path)

                # 为每个 chunk 添加 file_hash
                for chunk in chunks:
                    chunk.metadata["file_hash"] = file_hash

                all_chunks.extend(chunks)

                progress.processed_files += 1
                progress.added_files += 1
                progress.total_chunks = len(all_chunks)

                if progress_callback:
                    progress_callback(progress)
                yield progress

            except Exception as e:
                logger.warning(f"处理文件失败 {file_path}: {e}")
                progress.errors.append(f"{file_path}: {str(e)}")
                progress.processed_files += 1

        logger.info(f"📝 创建了 {len(all_chunks)} 个代码块")

        # 批量嵌入和索引
        if all_chunks:
            # 🔥 发送嵌入向量生成状态
            progress.status_message = f"🔢 生成 {len(all_chunks)} 个代码块的嵌入向量..."
            yield progress

            await self._index_chunks(all_chunks, progress, use_upsert=False, embedding_progress_callback=embedding_progress_callback, cancel_check=cancel_check)

        # 更新 collection 元数据
        project_hash = hashlib.md5(json.dumps(sorted(file_hashes.items())).encode()).hexdigest()
        await self.vector_store.update_collection_metadata({
            "project_hash": project_hash,
            "file_count": len(file_hashes),
        })

        progress.indexed_chunks = len(all_chunks)
        logger.info(f"✅ 全量索引完成: {progress.added_files} 个文件, {len(all_chunks)} 个代码块")
        yield progress

    async def _incremental_index(
        self,
        directory: str,
        exclude_patterns: List[str],
        include_patterns: Optional[List[str]],
        progress: IndexingProgress,
        progress_callback: Optional[Callable[[IndexingProgress], None]],
        embedding_progress_callback: Optional[Callable[[int, int], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> AsyncGenerator[IndexingProgress, None]:
        """增量索引"""
        logger.info("📝 开始增量索引...")

        # 获取已索引文件的 hash
        indexed_file_hashes = await self.vector_store.get_file_hashes()
        indexed_files = set(indexed_file_hashes.keys())

        logger.debug(f"📂 已索引文件数: {len(indexed_files)}, file_hashes: {list(indexed_file_hashes.keys())[:5]}...")

        # 收集当前文件
        current_files = self._collect_files(directory, exclude_patterns, include_patterns)
        current_file_map: Dict[str, str] = {}  # relative_path -> absolute_path

        for file_path in current_files:
            relative_path = os.path.relpath(file_path, directory)
            current_file_map[relative_path] = file_path

        current_file_set = set(current_file_map.keys())

        logger.debug(f"📁 当前文件数: {len(current_file_set)}, 示例: {list(current_file_set)[:5]}...")

        # 计算差异
        files_to_add = current_file_set - indexed_files
        files_to_delete = indexed_files - current_file_set
        files_to_check = current_file_set & indexed_files

        logger.debug(f"📊 差异分析: 交集={len(files_to_check)}, 新增候选={len(files_to_add)}, 删除候选={len(files_to_delete)}")

        # 检查需要更新的文件（hash 变化）
        files_to_update: Set[str] = set()
        for relative_path in files_to_check:
            file_path = current_file_map[relative_path]
            try:
                # 异步读取文件，避免阻塞事件循环
                content = await asyncio.to_thread(
                    self._read_file_sync, file_path
                )
                current_hash = hashlib.md5(content.encode()).hexdigest()
                if current_hash != indexed_file_hashes.get(relative_path):
                    files_to_update.add(relative_path)
            except Exception:
                files_to_update.add(relative_path)

        total_operations = len(files_to_add) + len(files_to_delete) + len(files_to_update)
        progress.total_files = total_operations

        logger.info(f"📊 增量更新: 新增 {len(files_to_add)}, 删除 {len(files_to_delete)}, 更新 {len(files_to_update)}")
        yield progress

        # 删除已移除的文件
        for relative_path in files_to_delete:
            progress.current_file = f"删除: {relative_path}"
            deleted_count = await self.vector_store.delete_by_file_path(relative_path)
            progress.deleted_files += 1
            progress.processed_files += 1
            logger.debug(f"🗑️ 删除文件 '{relative_path}' 的 {deleted_count} 个代码块")

            if progress_callback:
                progress_callback(progress)
            yield progress

        # 处理新增和更新的文件
        files_to_process = files_to_add | files_to_update
        all_chunks: List[CodeChunk] = []
        file_hashes: Dict[str, str] = dict(indexed_file_hashes)

        for relative_path in files_to_process:
            file_path = current_file_map[relative_path]
            progress.current_file = relative_path
            is_update = relative_path in files_to_update

            try:
                # 异步读取文件，避免阻塞事件循环
                content = await asyncio.to_thread(
                    self._read_file_sync, file_path
                )

                if not content.strip():
                    progress.processed_files += 1
                    progress.skipped_files += 1
                    continue

                # 如果是更新，先删除旧的
                if is_update:
                    await self.vector_store.delete_by_file_path(relative_path)

                # 计算文件 hash
                file_hash = hashlib.md5(content.encode()).hexdigest()
                file_hashes[relative_path] = file_hash

                # 限制文件大小
                if len(content) > 500000:
                    content = content[:500000]

                # 异步分块，避免 Tree-sitter 解析阻塞事件循环
                chunks = await self.splitter.split_file_async(content, relative_path)

                # 为每个 chunk 添加 file_hash
                for chunk in chunks:
                    chunk.metadata["file_hash"] = file_hash

                all_chunks.extend(chunks)

                progress.processed_files += 1
                if is_update:
                    progress.updated_files += 1
                else:
                    progress.added_files += 1
                progress.total_chunks += len(chunks)

                if progress_callback:
                    progress_callback(progress)
                yield progress

            except Exception as e:
                logger.warning(f"处理文件失败 {file_path}: {e}")
                progress.errors.append(f"{file_path}: {str(e)}")
                progress.processed_files += 1

        # 批量嵌入和索引新的代码块
        if all_chunks:
            # 🔥 发送嵌入向量生成状态
            progress.status_message = f"🔢 生成 {len(all_chunks)} 个代码块的嵌入向量..."
            yield progress

            await self._index_chunks(all_chunks, progress, use_upsert=True, embedding_progress_callback=embedding_progress_callback, cancel_check=cancel_check)

        # 更新 collection 元数据
        # 移除已删除文件的 hash
        for relative_path in files_to_delete:
            file_hashes.pop(relative_path, None)

        project_hash = hashlib.md5(json.dumps(sorted(file_hashes.items())).encode()).hexdigest()
        await self.vector_store.update_collection_metadata({
            "project_hash": project_hash,
            "file_count": len(file_hashes),
        })

        progress.indexed_chunks = len(all_chunks)
        logger.info(
            f"✅ 增量索引完成: 新增 {progress.added_files}, "
            f"更新 {progress.updated_files}, 删除 {progress.deleted_files}"
        )
        yield progress

    # 保留原有的 index_directory 方法作为兼容
    async def index_directory(
        self,
        directory: str,
        exclude_patterns: Optional[List[str]] = None,
        include_patterns: Optional[List[str]] = None,
        progress_callback: Optional[Callable[[IndexingProgress], None]] = None,
    ) -> AsyncGenerator[IndexingProgress, None]:
        """
        索引目录（使用智能模式）

        Args:
            directory: 目录路径
            exclude_patterns: 排除模式
            include_patterns: 包含模式
            progress_callback: 进度回调

        Yields:
            索引进度
        """
        async for progress in self.smart_index_directory(
            directory=directory,
            exclude_patterns=exclude_patterns,
            include_patterns=include_patterns,
            update_mode=IndexUpdateMode.SMART,
            progress_callback=progress_callback,
        ):
            yield progress

    async def index_files(
        self,
        files: List[Dict[str, str]],
        base_path: str = "",
        progress_callback: Optional[Callable[[IndexingProgress], None]] = None,
    ) -> AsyncGenerator[IndexingProgress, None]:
        """
        索引文件列表

        Args:
            files: 文件列表 [{"path": "...", "content": "..."}]
            base_path: 基础路径
            progress_callback: 进度回调

        Yields:
            索引进度
        """
        await self.initialize()

        progress = IndexingProgress()
        progress.total_files = len(files)

        all_chunks: List[CodeChunk] = []

        for file_info in files:
            file_path = file_info.get("path", "")
            content = file_info.get("content", "")

            progress.current_file = file_path

            try:
                if not content.strip():
                    progress.processed_files += 1
                    progress.skipped_files += 1
                    continue

                # 计算文件 hash
                file_hash = hashlib.md5(content.encode()).hexdigest()

                # 限制文件大小
                if len(content) > 500000:
                    content = content[:500000]

                # 分块
                chunks = self.splitter.split_file(content, file_path)

                # 为每个 chunk 添加 file_hash
                for chunk in chunks:
                    chunk.metadata["file_hash"] = file_hash

                all_chunks.extend(chunks)

                progress.processed_files += 1
                progress.added_files += 1
                progress.total_chunks = len(all_chunks)

                if progress_callback:
                    progress_callback(progress)
                yield progress

            except Exception as e:
                logger.warning(f"处理文件失败 {file_path}: {e}")
                progress.errors.append(f"{file_path}: {str(e)}")
                progress.processed_files += 1

        # 批量嵌入和索引
        if all_chunks:
            await self._index_chunks(all_chunks, progress, use_upsert=True)

        progress.indexed_chunks = len(all_chunks)
        yield progress

    async def _index_chunks(
        self,
        chunks: List[CodeChunk],
        progress: IndexingProgress,
        use_upsert: bool = False,
        embedding_progress_callback: Optional[Callable[[int, int], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
    ):
        """索引代码块

        Args:
            chunks: 代码块列表
            progress: 索引进度对象
            use_upsert: 是否使用 upsert（增量更新）
            embedding_progress_callback: 嵌入进度回调
            cancel_check: 取消检查函数，返回 True 表示应该取消
        """
        if not chunks:
            return

        # 去重：确保没有重复的 ID
        seen_ids: Set[str] = set()
        unique_chunks: List[CodeChunk] = []
        for chunk in chunks:
            if chunk.id not in seen_ids:
                seen_ids.add(chunk.id)
                unique_chunks.append(chunk)
            else:
                logger.warning(f"跳过重复 ID 的代码块: {chunk.id} ({chunk.file_path}:{chunk.line_start})")

        if len(unique_chunks) < len(chunks):
            logger.info(f"🔄 去重: {len(chunks)} -> {len(unique_chunks)} 个代码块")

        chunks = unique_chunks

        # 准备嵌入文本
        texts = [chunk.to_embedding_text() for chunk in chunks]

        logger.info(f"🔢 生成 {len(texts)} 个代码块的嵌入向量...")

        # 批量嵌入（带进度回调和取消检查）
        embeddings = await self.embedding_service.embed_batch(
            texts,
            batch_size=getattr(self.embedding_service, 'batch_size', 100),
            progress_callback=embedding_progress_callback,
            cancel_check=cancel_check,
        )

        # 准备元数据
        ids = [chunk.id for chunk in chunks]
        documents = [chunk.content for chunk in chunks]
        metadatas = [chunk.to_dict() for chunk in chunks]

        # 添加到向量存储
        logger.info(f"💾 添加 {len(chunks)} 个代码块到向量存储...")

        if use_upsert:
            await self.vector_store.upsert_documents(
                ids=ids,
                embeddings=embeddings,
                documents=documents,
                metadatas=metadatas,
            )
        else:
            await self.vector_store.add_documents(
                ids=ids,
                embeddings=embeddings,
                documents=documents,
                metadatas=metadatas,
            )

        logger.info(f"✅ 索引 {len(chunks)} 个代码块成功")

    def _collect_files(
        self,
        directory: str,
        exclude_patterns: List[str],
        include_patterns: Optional[List[str]],
    ) -> List[str]:
        """收集需要索引的文件"""
        import fnmatch

        files = []

        for root, dirs, filenames in os.walk(directory):
            # 过滤目录
            dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]

            for filename in filenames:
                # 检查扩展名
                ext = os.path.splitext(filename)[1].lower()
                if ext not in TEXT_EXTENSIONS:
                    continue

                # 检查排除文件
                if filename in EXCLUDE_FILES:
                    continue

                file_path = os.path.join(root, filename)
                relative_path = os.path.relpath(file_path, directory)

                # 检查排除模式
                excluded = False
                for pattern in exclude_patterns:
                    if fnmatch.fnmatch(relative_path, pattern) or fnmatch.fnmatch(filename, pattern):
                        excluded = True
                        break

                if excluded:
                    continue

                # 检查包含模式
                if include_patterns:
                    included = False
                    for pattern in include_patterns:
                        if fnmatch.fnmatch(relative_path, pattern) or fnmatch.fnmatch(filename, pattern):
                            included = True
                            break
                    if not included:
                        continue

                files.append(file_path)

        return files

    async def get_chunk_count(self) -> int:
        """获取已索引的代码块数量"""
        await self.initialize()
        return await self.vector_store.get_count()

    async def clear(self):
        """清空索引"""
        await self.initialize()
        await self.vector_store.delete_collection()
        self._initialized = False

    async def delete_file(self, file_path: str) -> int:
        """
        删除指定文件的索引

        Args:
            file_path: 文件路径

        Returns:
            删除的代码块数量
        """
        await self.initialize()
        return await self.vector_store.delete_by_file_path(file_path)

    async def rebuild(self, directory: str, **kwargs) -> AsyncGenerator[IndexingProgress, None]:
        """
        强制重建索引

        Args:
            directory: 目录路径
            **kwargs: 传递给 smart_index_directory 的其他参数

        Yields:
            索引进度
        """
        # 强制重新初始化
        self._initialized = False
        await self.initialize(force_rebuild=True)

        async for progress in self.smart_index_directory(
            directory=directory,
            update_mode=IndexUpdateMode.FULL,
            **kwargs,
        ):
            yield progress


