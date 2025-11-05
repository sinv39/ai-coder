"""
MCP服务器管理器
负责发现、缓存和管理MCP服务器及其工具
"""

import json
import os
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict
import requests

logger = logging.getLogger(__name__)


@dataclass
class MCPServer:
    """MCP服务器信息"""
    id: str
    name: str
    description: str
    url: str
    enabled: bool = True
    category: Optional[str] = None
    tags: List[str] = None
    
    def __post_init__(self):
        if self.tags is None:
            self.tags = []


@dataclass
class ToolInfo:
    """工具信息"""
    name: str
    description: str
    server_id: str
    server_url: str
    parameters: Dict[str, Any]
    category: Optional[str] = None
    tags: List[str] = None
    
    def __post_init__(self):
        if self.tags is None:
            self.tags = []
        if self.parameters is None:
            self.parameters = {}


class MCPServerManager:
    """MCP服务器管理器"""
    
    def __init__(self, config_path: str = "mcp_servers.json"):
        """
        初始化MCP服务器管理器
        
        Args:
            config_path: 服务器配置文件路径
        """
        self.config_path = config_path
        self.servers: Dict[str, MCPServer] = {}
        self.tools: Dict[str, ToolInfo] = {}  # key: f"{server_id}:{tool_name}"
        self.tools_cache: Dict[str, List[Dict]] = {}  # 缓存每个服务器的工具列表
        self.cache_timestamps: Dict[str, datetime] = {}
        self.cache_ttl = timedelta(seconds=3600)
        
        # 加载配置
        self.load_config()
    
    def load_config(self):
        """从配置文件加载服务器列表"""
        try:
            if os.path.exists(self.config_path):
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                
                # 加载服务器配置
                for server_config in config.get("servers", []):
                    if server_config.get("enabled", True):
                        server = MCPServer(**server_config)
                        self.servers[server.id] = server
                
                # 加载缓存配置
                cache_config = config.get("cache", {})
                if cache_config.get("enabled", True):
                    self.cache_ttl = timedelta(seconds=cache_config.get("ttl", 3600))
                
                logger.info(f"✅ 加载了 {len(self.servers)} 个MCP服务器配置")
            else:
                logger.warning(f"⚠️  配置文件不存在: {self.config_path}")
        except Exception as e:
            logger.error(f"❌ 加载配置文件失败: {e}")
    
    def discover_tools(self, server_id: Optional[str] = None, force_refresh: bool = False) -> Dict[str, List[ToolInfo]]:
        """
        发现MCP服务器上的工具
        
        Args:
            server_id: 服务器ID，如果为None则发现所有服务器
            force_refresh: 是否强制刷新缓存
        
        Returns:
            工具字典 {server_id: [ToolInfo]}
        """
        discovered_tools = {}
        
        servers_to_discover = []
        if server_id:
            if server_id in self.servers:
                servers_to_discover = [self.servers[server_id]]
            else:
                logger.warning(f"⚠️  服务器 {server_id} 不存在")
                return {}
        else:
            servers_to_discover = list(self.servers.values())
        
        for server in servers_to_discover:
            if not server.enabled:
                continue
            
            # 先检查服务器健康状态，如果不健康则跳过（不返回工具，即使有缓存）
            if not self.check_server_health(server.id):
                logger.warning(f"⚠️  服务器 {server.name} ({server.id}) 不健康，跳过工具发现")
                # 清除该服务器的缓存，避免下次仍使用过期缓存
                self._clear_cache(server.id)
                continue
            
            # 检查缓存
            if not force_refresh and self._is_cache_valid(server.id):
                logger.info(f"📋 使用缓存工具列表: {server.name}")
                tools = self._get_tools_from_cache(server.id)
                discovered_tools[server.id] = tools
                continue
            
            # 从服务器发现工具
            try:
                tools = self._discover_tools_from_server(server)
                discovered_tools[server.id] = tools
                
                # 更新缓存
                self._update_cache(server.id, tools)
                
            except Exception as e:
                logger.error(f"❌ 发现服务器 {server.name} 的工具失败: {e}")
                # 服务器不健康时，不再使用缓存，直接跳过
                # 这样LLM不会看到不可用的工具
        
        return discovered_tools
    
    def _discover_tools_from_server(self, server: MCPServer) -> List[ToolInfo]:
        """从服务器获取工具列表"""
        url = server.url.rstrip('/')
        
        payload = {
            "jsonrpc": "2.0",
            "method": "tools/list",
            "id": 1
        }
        
        try:
            response = requests.post(
                url,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=10
            )
            
            if response.status_code != 200:
                raise Exception(f"HTTP {response.status_code}: {response.text}")
            
            result = response.json()
            
            if "error" in result:
                raise Exception(result["error"].get("message", "未知错误"))
            
            tools_data = result.get("result", {}).get("tools", [])
            
            tools = []
            for tool_data in tools_data:
                # 处理不同的参数格式（parameters 或 inputSchema）
                parameters = tool_data.get("parameters") or tool_data.get("inputSchema", {})
                
                tool_info = ToolInfo(
                    name=tool_data.get("name", ""),
                    description=tool_data.get("description", ""),
                    server_id=server.id,
                    server_url=server.url,
                    parameters=parameters,
                    category=server.category,
                    tags=server.tags.copy()
                )
                tools.append(tool_info)
                
                # 更新工具字典
                tool_key = f"{server.id}:{tool_info.name}"
                self.tools[tool_key] = tool_info
            
            logger.info(f"✅ 发现服务器 {server.name} 的 {len(tools)} 个工具")
            return tools
            
        except requests.exceptions.RequestException as e:
            raise Exception(f"连接服务器失败: {str(e)}")
    
    def _is_cache_valid(self, server_id: str) -> bool:
        """检查缓存是否有效"""
        if server_id not in self.cache_timestamps:
            return False
        return datetime.now() - self.cache_timestamps[server_id] < self.cache_ttl
    
    def _get_tools_from_cache(self, server_id: str) -> List[ToolInfo]:
        """从缓存获取工具列表"""
        if server_id not in self.tools_cache:
            return []
        
        tools = []
        for tool_data in self.tools_cache[server_id]:
            tool_info = ToolInfo(**tool_data)
            tools.append(tool_info)
        
        return tools
    
    def _update_cache(self, server_id: str, tools: List[ToolInfo]):
        """更新缓存"""
        self.tools_cache[server_id] = [asdict(tool) for tool in tools]
        self.cache_timestamps[server_id] = datetime.now()
    
    def _clear_cache(self, server_id: str):
        """清除指定服务器的缓存"""
        if server_id in self.tools_cache:
            del self.tools_cache[server_id]
        if server_id in self.cache_timestamps:
            del self.cache_timestamps[server_id]
        logger.info(f"🗑️  已清除服务器 {server_id} 的缓存")
    
    def get_all_tools(self, force_refresh: bool = False) -> List[ToolInfo]:
        """获取所有工具"""
        discovered = self.discover_tools(force_refresh=force_refresh)
        all_tools = []
        for tools_list in discovered.values():
            all_tools.extend(tools_list)
        return all_tools
    
    def get_tool(self, server_id: str, tool_name: str) -> Optional[ToolInfo]:
        """获取特定工具"""
        tool_key = f"{server_id}:{tool_name}"
        if tool_key in self.tools:
            return self.tools[tool_key]
        return None
    
    def check_server_health(self, server_id: str) -> bool:
        """检查服务器健康状态"""
        if server_id not in self.servers:
            return False
        
        server = self.servers[server_id]
        try:
            health_url = f"{server.url.rstrip('/')}/health"
            response = requests.get(health_url, timeout=5)
            return response.status_code == 200
        except:
            return False
    
    def refresh_all_tools(self):
        """刷新所有工具（强制）"""
        return self.discover_tools(force_refresh=True)

