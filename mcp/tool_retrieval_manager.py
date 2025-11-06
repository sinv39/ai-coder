"""
工具检索管理器
管理MCP工具的MongoDB存储，提供工具信息查询功能
"""

import json
import hashlib
import logging
import threading
import time
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime
from dataclasses import asdict

from mcp_server_manager import MCPServerManager, ToolInfo, MCPServer
from mongodb_client import MongoDBClient

logger = logging.getLogger(__name__)


class ToolRetrievalManager:
    """工具检索管理器"""
    
    def __init__(self, server_manager: MCPServerManager,
                 mongo_host: str = "localhost", mongo_port: int = 27017,
                 mongo_database: str = None, mongo_username: str = None, mongo_password: str = None,
                 refresh_interval: int = 600):  # 默认10分钟刷新
        """
        初始化工具检索管理器
        
        Args:
            server_manager: MCP服务器管理器
            mongo_host: MongoDB主机
            mongo_port: MongoDB端口
            mongo_database: MongoDB数据库名称（可选）
            mongo_username: MongoDB用户名（可选）
            mongo_password: MongoDB密码（可选）
            refresh_interval: 自动刷新间隔（秒），默认10分钟
        """
        self.server_manager = server_manager
        self.mongo_client = MongoDBClient(
            host=mongo_host, 
            port=mongo_port,
            database=mongo_database,
            username=mongo_username,
            password=mongo_password
        )
        self.refresh_interval = refresh_interval
        
        # 创建集合（如果不存在）
        self.mongo_client.create_index(force=False)
        
        # 后台刷新线程
        self._refresh_thread: Optional[threading.Thread] = None
        self._stop_refresh = False
        
        logger.info("✅ 工具检索管理器初始化完成")
    
    def _generate_tool_version(self, tool_info: ToolInfo) -> str:
        """
        生成工具版本号（基于工具内容hash）
        
        Args:
            tool_info: 工具信息
            
        Returns:
            16位hash字符串
        """
        version_data = {
            "name": tool_info.name,
            "description": tool_info.description,
            "parameters": tool_info.parameters,
            "server_id": tool_info.server_id,
            "category": tool_info.category,
            "tags": sorted(tool_info.tags) if tool_info.tags else []
        }
        
        version_str = json.dumps(version_data, sort_keys=True, ensure_ascii=False)
        hash_value = hashlib.sha256(version_str.encode('utf-8')).hexdigest()
        return hash_value[:16]
    
    def _generate_server_version(self, server: MCPServer) -> str:
        """
        生成服务器配置版本号
        
        Args:
            server: 服务器信息
            
        Returns:
            16位hash字符串
        """
        version_data = {
            "id": server.id,
            "name": server.name,
            "description": server.description,
            "url": server.url,
            "category": server.category,
            "tags": sorted(server.tags) if server.tags else []
        }
        
        version_str = json.dumps(version_data, sort_keys=True, ensure_ascii=False)
        hash_value = hashlib.sha256(version_str.encode('utf-8')).hexdigest()
        return hash_value[:16]
    
    def _build_search_text(self, tool_info: ToolInfo, server: MCPServer) -> str:
        """
        构建用于检索的文本
        
        Args:
            tool_info: 工具信息
            server: 服务器信息
            
        Returns:
            检索文本
        """
        parts = [
            f"工具名称: {tool_info.name}",
            f"工具描述: {tool_info.description}",
            f"服务器名称: {server.name}",
            f"服务器描述: {server.description}"
        ]
        
        if tool_info.category:
            parts.append(f"类别: {tool_info.category}")
        
        if tool_info.tags:
            parts.append(f"标签: {', '.join(tool_info.tags)}")
        
        # 添加参数描述
        params = tool_info.parameters
        if params and isinstance(params, dict):
            properties = params.get("properties", {})
            if properties:
                param_descriptions = []
                for param_name, param_info in properties.items():
                    param_desc = param_info.get("description", "")
                    if param_desc:
                        param_descriptions.append(f"{param_name}: {param_desc}")
                if param_descriptions:
                    parts.append(f"参数: {', '.join(param_descriptions)}")
        
        return "\n".join(parts)
    
    def _build_tool_document(self, tool_info: ToolInfo, server: MCPServer) -> Dict[str, Any]:
        """
        构建工具文档（用于索引）
        
        Args:
            tool_info: 工具信息
            server: 服务器信息
            
        Returns:
            工具文档字典
        """
        tool_id = f"{tool_info.server_id}:{tool_info.name}"
        now = datetime.now().isoformat()
        
        return {
            "tool_id": tool_id,
            "tool_name": tool_info.name,
            "tool_description": tool_info.description,
            "tool_parameters": tool_info.parameters,  # 存储完整的参数定义
            "server_id": tool_info.server_id,
            "server_name": server.name,
            "category": tool_info.category or server.category,
            "tags": tool_info.tags or server.tags or [],
            "search_text": self._build_search_text(tool_info, server),
            "tool_version": self._generate_tool_version(tool_info),
            "server_version": self._generate_server_version(server),
            "last_discovered_at": now,
            "indexed_at": now
        }
    
    def build_index(self) -> int:
        """
        构建完整索引（基于当前配置文件）
        
        Returns:
            索引的工具数量
        """
        logger.info("开始构建工具索引...")
        
        # 发现所有工具（强制刷新）
        discovered_tools = self.server_manager.discover_tools(force_refresh=True)
        
        all_tools_info = []
        for tools_list in discovered_tools.values():
            all_tools_info.extend(tools_list)
        
        if not all_tools_info:
            logger.warning("没有发现任何工具")
            return 0
        
        logger.info(f"发现 {len(all_tools_info)} 个工具，开始构建索引...")
        
        # 构建工具文档
        tool_docs = []
        
        for tool_info in all_tools_info:
            server = self.server_manager.servers.get(tool_info.server_id)
            if not server:
                logger.warning(f"服务器 {tool_info.server_id} 不存在，跳过工具 {tool_info.name}")
                continue
            
            tool_doc = self._build_tool_document(tool_info, server)
            tool_docs.append(tool_doc)
        
        # 批量索引
        success_count = self.mongo_client.index_tools_batch(tool_docs)
        logger.info(f"✅ 索引构建完成: {success_count}/{len(tool_docs)} 个工具")
        
        return success_count
    
    def detect_tool_changes(self) -> Dict[str, List[str]]:
        """
        检测工具变化
        
        Returns:
            变化检测结果字典
        """
        # 发现当前工具
        discovered_tools = self.server_manager.discover_tools(force_refresh=False)
        current_tools = []
        for tools_list in discovered_tools.values():
            current_tools.extend(tools_list)
        
        # 获取已索引的工具版本
        indexed_versions = self.mongo_client.get_tool_versions()
        
        # 计算当前工具的版本号
        current_map = {}
        for tool_info in current_tools:
            tool_id = f"{tool_info.server_id}:{tool_info.name}"
            current_map[tool_id] = self._generate_tool_version(tool_info)
        
        # 检测变化
        changes = {
            "added": [],
            "removed": [],
            "updated": [],
            "unchanged": []
        }
        
        # 检测新增和更新
        for tool_id, current_version in current_map.items():
            if tool_id not in indexed_versions:
                changes["added"].append(tool_id)
            elif indexed_versions[tool_id] != current_version:
                changes["updated"].append(tool_id)
            else:
                changes["unchanged"].append(tool_id)
        
        # 检测删除
        for tool_id in indexed_versions:
            if tool_id not in current_map:
                changes["removed"].append(tool_id)
        
        return changes
    
    def refresh_index_incremental(self) -> Dict[str, int]:
        """
        增量更新索引
        
        Returns:
            更新统计信息
        """
        logger.info("开始增量更新索引...")
        
        # 检测变化
        changes = self.detect_tool_changes()
        
        stats = {
            "added": 0,
            "updated": 0,
            "removed": 0,
            "unchanged": len(changes["unchanged"])
        }
        
        # 处理删除
        for tool_id in changes["removed"]:
            if self.mongo_client.delete_tool(tool_id):
                stats["removed"] += 1
        
        # 处理新增和更新
        tools_to_update = changes["added"] + changes["updated"]
        if tools_to_update:
            # 获取需要更新的工具信息
            discovered_tools = self.server_manager.discover_tools(force_refresh=False)
            all_tools_map = {}
            for tools_list in discovered_tools.values():
                for tool_info in tools_list:
                    tool_id = f"{tool_info.server_id}:{tool_info.name}"
                    all_tools_map[tool_id] = tool_info
            
            # 构建需要更新的工具文档
            tool_docs = []
            
            for tool_id in tools_to_update:
                tool_info = all_tools_map.get(tool_id)
                if not tool_info:
                    continue
                
                server = self.server_manager.servers.get(tool_info.server_id)
                if not server:
                    continue
                
                tool_doc = self._build_tool_document(tool_info, server)
                tool_docs.append(tool_doc)
            
            # 批量索引
            if tool_docs:
                try:
                    success_count = self.mongo_client.index_tools_batch(tool_docs)
                    stats["added"] = len([t for t in tools_to_update if t in changes["added"]])
                    stats["updated"] = success_count - stats["added"]
                except Exception as e:
                    logger.error(f"增量更新失败: {str(e)}")
        
        logger.info(f"✅ 增量更新完成: 新增 {stats['added']}, 更新 {stats['updated']}, "
                   f"删除 {stats['removed']}, 未变化 {stats['unchanged']}")
        
        return stats
    
    def search_tools(self, query: str, top_k: int = 3, min_score: float = 0.0) -> List[ToolInfo]:
        """
        搜索工具（文本搜索）
        
        Args:
            query: 查询文本
            top_k: 返回结果数量
            min_score: 最小分数阈值（MongoDB文本搜索暂不支持，保留参数以兼容）
            
        Returns:
            匹配的工具信息列表
        """
        # MongoDB文本搜索（简化版，基于关键词匹配）
        try:
            # 使用MongoDB的文本搜索（通过get_all_tools然后过滤）
            all_tools = self.mongo_client.get_all_tools()
            # 在内存中过滤匹配的工具
            results = []
            query_lower = query.lower()
            for tool in all_tools:
                tool_name = tool.get("tool_name", "").lower()
                tool_desc = tool.get("tool_description", "").lower()
                search_text = tool.get("search_text", "").lower()
                
                if (query_lower in tool_name or 
                    query_lower in tool_desc or 
                    query_lower in search_text):
                    results.append(tool)
                    if len(results) >= top_k:
                        break
            
            # 转换为ToolInfo对象
            tools = []
            for result in results:
                tool_id = result.get("tool_id")
                if not tool_id:
                    continue
                
                # 从server_manager获取原始ToolInfo
                server_id, tool_name = tool_id.split(":", 1)
                tool_info = self.server_manager.get_tool(server_id, tool_name)
                
                if tool_info:
                    tools.append(tool_info)
                else:
                    logger.warning(f"工具 {tool_id} 在server_manager中不存在")
            
            logger.info(f"检索到 {len(tools)} 个匹配的工具")
            return tools
        except Exception as e:
            logger.error(f"搜索工具失败: {str(e)}")
            return []
    
    def start_auto_refresh(self):
        """启动自动刷新线程"""
        if self._refresh_thread and self._refresh_thread.is_alive():
            logger.warning("自动刷新线程已在运行")
            return
        
        self._stop_refresh = False
        
        def refresh_loop():
            while not self._stop_refresh:
                try:
                    time.sleep(self.refresh_interval)
                    if not self._stop_refresh:
                        self.refresh_index_incremental()
                except Exception as e:
                    logger.error(f"自动刷新失败: {str(e)}")
        
        self._refresh_thread = threading.Thread(target=refresh_loop, daemon=True)
        self._refresh_thread.start()
        logger.info(f"✅ 自动刷新线程已启动，间隔: {self.refresh_interval}秒")
    
    def stop_auto_refresh(self):
        """停止自动刷新线程"""
        self._stop_refresh = True
        if self._refresh_thread:
            self._refresh_thread.join(timeout=5)
        logger.info("自动刷新线程已停止")

