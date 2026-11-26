"""
Agent 注册表和动态Agent树管理

提供：
- Agent实例注册和管理
- 动态Agent树结构
- Agent状态追踪
- 子Agent创建和销毁
"""

import logging
import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from .state import AgentState

logger = logging.getLogger(__name__)


class AgentRegistry:
    """
    Agent 注册表
    
    管理所有Agent实例，维护动态Agent树结构
    """
    
    def __init__(self):
        self._lock = threading.RLock()
        
        # Agent图结构
        self._agent_graph: Dict[str, Any] = {
            "nodes": {},  # agent_id -> node_info
            "edges": [],  # {from, to, type}
        }
        
        # Agent实例和状态
        self._agent_instances: Dict[str, Any] = {}  # agent_id -> agent_instance
        self._agent_states: Dict[str, "AgentState"] = {}  # agent_id -> state
        
        # 消息队列
        self._agent_messages: Dict[str, List[Dict[str, Any]]] = {}  # agent_id -> messages
        
        # 根Agent
        self._root_agent_id: Optional[str] = None
        
        # 运行中的Agent线程
        self._running_agents: Dict[str, threading.Thread] = {}
    
    # ============ Agent 注册 ============
    
    def register_agent(
        self,
        agent_id: str,
        agent_name: str,
        agent_type: str,
        task: str,
        parent_id: Optional[str] = None,
        agent_instance: Any = None,
        state: Optional["AgentState"] = None,
        knowledge_modules: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        注册Agent到注册表
        
        Args:
            agent_id: Agent唯一标识
            agent_name: Agent名称
            agent_type: Agent类型
            task: 任务描述
            parent_id: 父Agent ID
            agent_instance: Agent实例
            state: Agent状态
            knowledge_modules: 加载的知识模块
            
        Returns:
            注册的节点信息
        """
        logger.debug(f"[AgentRegistry] register_agent 被调用: {agent_name} (id={agent_id}, parent={parent_id})")
        logger.debug(f"[AgentRegistry] 当前节点数: {len(self._agent_graph['nodes'])}, 节点列表: {list(self._agent_graph['nodes'].keys())}")
        
        with self._lock:
            node = {
                "id": agent_id,
                "name": agent_name,
                "type": agent_type,
                "task": task,
                "status": "running",
                "parent_id": parent_id,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "finished_at": None,
                "result": None,
                "knowledge_modules": knowledge_modules or [],
                "children": [],
            }
            
            self._agent_graph["nodes"][agent_id] = node
            
            if agent_instance:
                self._agent_instances[agent_id] = agent_instance
            
            if state:
                self._agent_states[agent_id] = state
            
            # 初始化消息队列
            if agent_id not in self._agent_messages:
                self._agent_messages[agent_id] = []
            
            # 添加边（父子关系）
            if parent_id:
                self._agent_graph["edges"].append({
                    "from": parent_id,
                    "to": agent_id,
                    "type": "delegation",
                    "created_at": datetime.now(timezone.utc).isoformat(),
                })
                
                # 更新父节点的children列表
                if parent_id in self._agent_graph["nodes"]:
                    self._agent_graph["nodes"][parent_id]["children"].append(agent_id)
            
            # 设置根Agent
            if parent_id is None and self._root_agent_id is None:
                self._root_agent_id = agent_id
            
            logger.debug(f"[AgentRegistry] 注册完成: {agent_name} ({agent_id}), parent: {parent_id}")
            logger.debug(f"[AgentRegistry] 注册后节点数: {len(self._agent_graph['nodes'])}, 节点列表: {list(self._agent_graph['nodes'].keys())}")
            return node
    
    def unregister_agent(self, agent_id: str) -> None:
        """注销Agent"""
        with self._lock:
            if agent_id in self._agent_graph["nodes"]:
                node = self._agent_graph["nodes"].pop(agent_id)
                parent = self._agent_graph["nodes"].get(node.get("parent_id"))
                if parent and agent_id in parent["children"]:
                    parent["children"].remove(agent_id)
                if self._root_agent_id == agent_id:
                    self._root_agent_id = next((aid for aid, n in self._agent_graph["nodes"].items()
                                                if n["parent_id"] is None), None)
            
            self._agent_instances.pop(agent_id, None)
            self._agent_states.pop(agent_id, None)
            self._agent_messages.pop(agent_id, None)
            self._running_agents.pop(agent_id, None)
            
            # 移除相关边
            self._agent_graph["edges"] = [
                e for e in self._agent_graph["edges"]
                if e["from"] != agent_id and e["to"] != agent_id
            ]
            
            logger.debug(f"Unregistered agent: {agent_id}")
    
    # ============ Agent 状态更新 ============
    
    def update_agent_status(
        self,
        agent_id: str,
        status: str,
        result: Optional[Dict[str, Any]] = None,
    ) -> None:
        """更新Agent状态"""
        with self._lock:
            if agent_id in self._agent_graph["nodes"]:
                node = self._agent_graph["nodes"][agent_id]
                node["status"] = status
                
                if status in ["completed", "failed", "stopped"]:
                    node["finished_at"] = datetime.now(timezone.utc).isoformat()
                
                if result:
                    node["result"] = result
                
                logger.debug(f"Updated agent {agent_id} status to {status}")
    
    def get_agent_status(self, agent_id: str) -> Optional[str]:
        """获取Agent状态"""
        with self._lock:
            if agent_id in self._agent_graph["nodes"]:
                return self._agent_graph["nodes"][agent_id]["status"]
            return None
    
    # ============ Agent 查询 ============
    
    def get_agent(self, agent_id: str) -> Optional[Any]:
        """获取Agent实例"""
        return self._agent_instances.get(agent_id)
    
    def get_agent_state(self, agent_id: str) -> Optional["AgentState"]:
        """获取Agent状态"""
        return self._agent_states.get(agent_id)
    
    def get_agent_node(self, agent_id: str) -> Optional[Dict[str, Any]]:
        """获取Agent节点信息"""
        return self._agent_graph["nodes"].get(agent_id)
    
    def get_root_agent_id(self) -> Optional[str]:
        """获取根Agent ID"""
        return self._root_agent_id
    
    def get_children(self, agent_id: str) -> List[str]:
        """获取子Agent ID列表"""
        with self._lock:
            node = self._agent_graph["nodes"].get(agent_id)
            if node:
                return node.get("children", [])
            return []
    
    def get_parent(self, agent_id: str) -> Optional[str]:
        """获取父Agent ID"""
        with self._lock:
            node = self._agent_graph["nodes"].get(agent_id)
            if node:
                return node.get("parent_id")
            return None
    
    # ============ Agent 树操作 ============
    
    def get_agent_tree(self) -> Dict[str, Any]:
        """获取完整的Agent树结构"""
        with self._lock:
            return {
                "nodes": dict(self._agent_graph["nodes"]),
                "edges": list(self._agent_graph["edges"]),
                "root_agent_id": self._root_agent_id,
            }
    
    def get_agent_tree_view(self, agent_id: Optional[str] = None) -> str:
        """获取Agent树的文本视图"""
        with self._lock:
            lines = ["=== AGENT TREE ==="]
            
            root_id = agent_id or self._root_agent_id
            if not root_id or root_id not in self._agent_graph["nodes"]:
                return "No agents in the tree"
            
            def _build_tree(aid: str, depth: int = 0) -> None:
                node = self._agent_graph["nodes"].get(aid)
                if not node:
                    return
                
                indent = "  " * depth
                status_emoji = {
                    "running": "🔄",
                    "waiting": "⏳",
                    "completed": "✅",
                    "failed": "❌",
                    "stopped": "🛑",
                }.get(node["status"], "❓")
                
                lines.append(f"{indent}{status_emoji} {node['name']} ({aid})")
                lines.append(f"{indent}   Task: {node['task'][:50]}...")
                lines.append(f"{indent}   Status: {node['status']}")
                
                if node.get("knowledge_modules"):
                    lines.append(f"{indent}   Modules: {', '.join(node['knowledge_modules'])}")
                
                for child_id in node.get("children", []):
                    _build_tree(child_id, depth + 1)
            
            _build_tree(root_id)
            return "\n".join(lines)
    
    def get_statistics(self) -> Dict[str, int]:
        """获取统计信息"""
        with self._lock:
            stats = {
                "total": len(self._agent_graph["nodes"]),
                "running": 0,
                "waiting": 0,
                "completed": 0,
                "failed": 0,
                "stopped": 0,
            }
            
            for node in self._agent_graph["nodes"].values():
                status = node.get("status", "unknown")
                if status in stats:
                    stats[status] += 1
            
            return stats
    
    # ============ 清理 ============
    
    def clear(self) -> None:
        """清空注册表"""
        with self._lock:
            self._agent_graph = {"nodes": {}, "edges": []}
            self._agent_instances.clear()
            self._agent_states.clear()
            self._agent_messages.clear()
            self._running_agents.clear()
            self._root_agent_id = None
            logger.debug("Agent registry cleared")
    
    def cleanup_finished_agents(self) -> int:
        """清理已完成的Agent"""
        with self._lock:
            finished_ids = [
                aid for aid, node in self._agent_graph["nodes"].items()
                if node["status"] in ["completed", "failed", "stopped"]
            ]
            
            for aid in finished_ids:
                # 保留节点信息，但清理实例
                self._agent_instances.pop(aid, None)
                self._running_agents.pop(aid, None)
            
            return len(finished_ids)


# 全局注册表实例
agent_registry = AgentRegistry()
