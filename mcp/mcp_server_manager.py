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
    url: str
    type: str = "http"  # http, streamable_http, sse
    enabled: bool = True
    headers: Optional[Dict[str, str]] = None
    # 从initialize自动获取的信息
    name: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    tags: List[str] = None
    session_id: Optional[str] = None  # 用于streamable_http协议的会话ID
    requires_session: bool = False  # 是否需要会话管理
    server_info: Optional[Dict[str, Any]] = None  # initialize返回的完整信息
    
    def __post_init__(self):
        if self.tags is None:
            self.tags = []
        if self.headers is None:
            self.headers = {}
        # 根据type判断是否需要会话
        if self.type in ["streamable_http", "sse"]:
            self.requires_session = True


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
        
        # 检测并初始化需要会话的服务器（同时获取服务器信息）
        self._initialize_sessions()
        
        # 从工具列表自动推断category和tags（如果还没有）
        self._auto_discover_server_metadata()
    
    def load_config(self):
        """从配置文件加载服务器列表（Cursor标准格式）"""
        try:
            if os.path.exists(self.config_path):
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                
                # Cursor标准格式：只支持mcpServers对象
                mcp_servers = config.get("mcpServers", {})
                
                if not isinstance(mcp_servers, dict):
                    logger.error("❌ 配置格式错误: mcpServers 必须是对象")
                    return
                
                for server_id, server_config in mcp_servers.items():
                    if not isinstance(server_config, dict):
                        logger.warning(f"⚠️  服务器 {server_id} 配置格式错误，跳过")
                        continue
                    
                    # 验证必需字段
                    url = server_config.get("url")
                    if not url:
                        logger.warning(f"⚠️  服务器 {server_id} 缺少url字段，跳过")
                        continue
                    
                    # 处理headers中的环境变量替换
                    headers = server_config.get("headers")
                    if headers and isinstance(headers, dict):
                        processed_headers = {}
                        for key, value in headers.items():
                            if isinstance(value, str):
                                # 支持在字符串中替换环境变量，格式: ${VAR_NAME} 或 "Bearer ${VAR_NAME}"
                                import re
                                def replace_env_var(match):
                                    env_var = match.group(1)
                                    env_value = os.getenv(env_var)
                                    if env_value:
                                        return env_value
                                    else:
                                        logger.warning(f"⚠️  环境变量 {env_var} 未设置，服务器 {server_id} 的 {key} header 将使用空值")
                                        return ""
                                # 替换所有 ${VAR_NAME} 格式的环境变量
                                processed_value = re.sub(r'\$\{([^}]+)\}', replace_env_var, value)
                                processed_headers[key] = processed_value
                            else:
                                processed_headers[key] = value
                        headers = processed_headers
                    
                    # 构建服务器对象（Cursor格式：只包含type, url, headers）
                    server = MCPServer(
                        id=server_id,
                        url=url,
                        type=server_config.get("type", "http"),  # 默认http
                        enabled=True,  # Cursor格式中，存在即启用，删除配置即禁用
                        headers=headers  # 可选
                    )
                    
                    self.servers[server.id] = server
                
                logger.info(f"✅ 加载了 {len(self.servers)} 个MCP服务器配置（Cursor格式）")
            else:
                logger.warning(f"⚠️  配置文件不存在: {self.config_path}")
        except json.JSONDecodeError as e:
            logger.error(f"❌ JSON解析失败: {e}")
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
        """从服务器获取工具列表（自定义实现）"""
        # 如果需要会话但还没有会话ID，先初始化
        if server.requires_session and not server.session_id:
            if not self._init_server_session(server):
                raise Exception("无法初始化服务器会话")
        
        # 对于 SSE 协议，使用返回的 endpoint URL
        if server.type == "sse" and server.server_info and server.server_info.get('sse_endpoint'):
            url = server.server_info['sse_endpoint']
            # SSE endpoint 需要 sessionId 作为查询参数
            if server.session_id:
                url = f"{url}?sessionId={server.session_id}"
        else:
            url = server.url.rstrip('/')
        
        payload = {
            "jsonrpc": "2.0",
            "method": "tools/list",
            "id": 1
        }
        
        try:
            # 对于 SSE 协议，需要使用 stream=True 来读取事件流
            stream = server.type == "sse"
            response = requests.post(
                url,
                json=payload,
                headers=self._get_request_headers(server),
                timeout=10,
                stream=stream
            )
            
            # SSE 协议可能返回 202 Accepted，这是正常的
            if server.type == "sse":
                if response.status_code not in [200, 202]:
                    raise Exception(f"HTTP {response.status_code}: {response.text}")
            else:
                if response.status_code != 200:
                    raise Exception(f"HTTP {response.status_code}: {response.text}")
            
            # 解析响应
            if server.type == "sse":
                # SSE 格式: data: {"jsonrpc": "2.0", ...}
                # 需要流式读取
                result = None
                try:
                    for line in response.iter_lines(decode_unicode=True):
                        if line and line.startswith('data:'):
                            json_str = line[5:].strip()  # 去掉 "data: " 前缀
                            try:
                                result = json.loads(json_str)
                                break  # 找到第一个有效响应
                            except json.JSONDecodeError:
                                continue
                    if result is None:
                        raise Exception("SSE 响应中未找到有效的 JSON 数据")
                except Exception as e:
                    raise Exception(f"解析 SSE 响应失败: {str(e)}")
            else:
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
            
            server_name = server.name or server.id
            logger.info(f"✅ 发现服务器 {server_name} 的 {len(tools)} 个工具")
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
            # 对于需要会话的服务器，尝试初始化或发送简单请求
            if server.requires_session:
                if not server.session_id:
                    return self._init_server_session(server)
                # 尝试发送一个简单的请求来检查会话是否有效
                try:
                    payload = {
                        "jsonrpc": "2.0",
                        "method": "tools/list",
                        "id": 0
                    }
                    response = requests.post(
                        server.url.rstrip('/'),
                        json=payload,
                        headers=self._get_request_headers(server),
                        timeout=5
                    )
                    return response.status_code == 200
                except:
                    # 如果请求失败，尝试重新初始化会话
                    return self._init_server_session(server)
            else:
                # 标准HTTP服务器，检查health端点
                health_url = f"{server.url.rstrip('/')}/health"
                response = requests.get(health_url, timeout=5)
                return response.status_code == 200
        except:
            return False
    
    def refresh_all_tools(self):
        """刷新所有工具（强制）"""
        return self.discover_tools(force_refresh=True)
    
    def _initialize_sessions(self):
        """初始化需要会话的服务器，并获取服务器信息"""
        for server_id, server in self.servers.items():
            if not server.enabled:
                continue
            
            # 对于所有启用的服务器，都尝试调用initialize获取信息
            # 这样可以从initialize响应中获取服务器信息（name, description等）
            try:
                self._init_server_session(server)
            except Exception as e:
                logger.warning(f"⚠️  初始化服务器 {server.id} 失败: {e}")
                # 如果初始化失败，设置默认值
                if not server.name:
                    server.name = server.id
                if not server.description:
                    server.description = f"MCP服务器: {server.id}"
    
    def _auto_discover_server_metadata(self):
        """从工具列表自动推断服务器的category和tags"""
        # 发现所有工具
        discovered_tools = self.discover_tools(force_refresh=False)
        
        # 为每个服务器推断metadata
        for server_id, server in self.servers.items():
            if not server.enabled:
                continue
            
            # 如果已经有category和tags，跳过
            if server.category and server.tags:
                continue
            
            tools = discovered_tools.get(server_id, [])
            if not tools:
                continue
            
            # 分析工具名称和描述，推断category
            if not server.category:
                category_keywords = {
                    "file": "file_operations",
                    "read": "file_operations",
                    "write": "file_operations",
                    "directory": "file_operations",
                    "time": "system",
                    "date": "system",
                    "mysql": "database",
                    "database": "database",
                    "sql": "database",
                    "query": "database",
                    "music": "music",
                    "song": "music",
                    "train": "travel",
                    "ticket": "travel",
                    "12306": "travel"
                }
                
                tool_names = " ".join([tool.name.lower() for tool in tools])
                tool_descriptions = " ".join([tool.description.lower() for tool in tools])
                combined_text = f"{tool_names} {tool_descriptions}"
                
                for keyword, category in category_keywords.items():
                    if keyword in combined_text:
                        server.category = category
                        break
            
            # 从工具名称提取tags
            if not server.tags:
                tags = set()
                for tool in tools:
                    # 从工具名称中提取关键词
                    name_parts = tool.name.lower().split("_")
                    for part in name_parts:
                        if len(part) > 2 and part not in ["get", "set", "list", "create", "delete", "update"]:
                            tags.add(part)
                
                server.tags = list(tags)[:5]  # 最多5个tags
            
            logger.debug(f"服务器 {server.id} 自动推断: category={server.category}, tags={server.tags}")
    
    def _init_server_session(self, server: MCPServer) -> bool:
        """初始化服务器会话，并从initialize响应中提取服务器信息"""
        try:
            # 对于 SSE 协议，DashScope 需要特殊的两步连接：
            # 1. 先用 GET 请求建立 SSE 连接，获取 endpoint 和 sessionId
            # 2. 然后使用返回的 endpoint 发送实际的请求
            if server.type == "sse":
                return self._init_sse_server_session(server)
            
            # 标准 HTTP 或 streamable_http 协议
            payload = {
                "jsonrpc": "2.0",
                "method": "initialize",
                "id": 1,
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {
                        "name": "python-mcp-client",
                        "version": "1.0.0"
                    }
                }
            }
            
            # 构建请求头
            headers = {
                "Content-Type": "application/json"
            }
            
            # 添加配置中的headers
            if server.headers:
                headers.update(server.headers)
            
            # streamable_http协议要求Accept头
            if server.type == "streamable_http":
                headers["Accept"] = "application/json, text/event-stream"
            
            response = requests.post(
                server.url.rstrip('/'),
                json=payload,
                headers=headers,
                timeout=10
            )
            
            # 检查响应
            if response.status_code != 200:
                # HTTP错误，使用默认值
                self._set_default_server_info(server)
                return False
            
            # 解析响应
            try:
                result = response.json()
                
                # 检查是否有错误（某些服务器不支持initialize方法）
                if "error" in result:
                    error_code = result.get("error", {}).get("code")
                    error_message = result.get("error", {}).get("message", "")
                    
                    # -32601 表示方法不存在，这是正常的（某些简化版MCP服务器不支持initialize）
                    if error_code == -32601 and "未知方法" in error_message or "Method not found" in error_message:
                        logger.debug(f"服务器 {server.id} 不支持 initialize 方法（这是正常的）")
                        self._set_default_server_info(server)
                        # 对于不支持initialize的服务器，仍然返回True（不算失败）
                        return True
                    else:
                        # 其他错误
                        logger.debug(f"服务器 {server.id} initialize 返回错误: {error_message}")
                        self._set_default_server_info(server)
                        return False
                
                # 成功响应
                initialize_result = result.get("result", {})
                
                # 从响应头中获取session-id（streamable_http协议）
                session_id = response.headers.get("mcp-session-id") or response.headers.get("Mcp-Session-Id")
                if not session_id:
                    session_id = initialize_result.get("sessionId")
                
                if session_id:
                    server.session_id = session_id
                    # 发送 initialized 通知（MCP协议要求）
                    self._send_initialized_notification(server)
                
                # 从initialize响应中提取服务器信息
                server_info = initialize_result.get("serverInfo", {})
                if server_info:
                    server.server_info = server_info
                    # 从initialize响应中获取name和description
                    server.name = server_info.get("name", server.id)
                    server.description = server_info.get("description", f"MCP服务器: {server.id}")
                else:
                    # 保存完整的initialize结果
                    server.server_info = initialize_result
                    # 如果没有serverInfo，使用默认值
                    if not server.name:
                        server.name = server.id
                    if not server.description:
                        server.description = f"MCP服务器: {server.id}"
                
                server_name = server.name or server.id
                if session_id:
                    logger.info(f"✅ 服务器 {server_name} 会话初始化成功")
                else:
                    logger.debug(f"服务器 {server_name} initialize 成功（无需会话）")
                
                return True
                
            except json.JSONDecodeError as e:
                logger.warning(f"服务器 {server.id} 响应不是有效的JSON: {e}")
                self._set_default_server_info(server)
                return False
                
        except requests.exceptions.RequestException as e:
            logger.warning(f"服务器 {server.id} 连接失败: {e}")
            self._set_default_server_info(server)
            return False
        except Exception as e:
            logger.warning(f"初始化服务器 {server.id} 时出错: {e}")
            self._set_default_server_info(server)
            return False
    
    def _init_sse_server_session(self, server: MCPServer) -> bool:
        """
        初始化 SSE 服务器会话（DashScope 特殊实现）
        DashScope SSE 端点需要两步连接：
        1. GET 请求建立连接，获取 endpoint 和 sessionId
        2. 使用返回的 endpoint 发送实际请求
        """
        try:
            # 第一步：GET 请求建立 SSE 连接
            headers = {
                "Accept": "text/event-stream"
            }
            
            # 添加配置中的headers（如 Authorization）
            if server.headers:
                headers.update(server.headers)
            
            logger.debug(f"建立 SSE 连接到: {server.url}")
            response = requests.get(
                server.url.rstrip('/'),
                headers=headers,
                timeout=10,
                stream=True
            )
            
            if response.status_code != 200:
                logger.warning(f"SSE 连接失败: HTTP {response.status_code}")
                self._set_default_server_info(server)
                return False
            
            # 解析 SSE 事件流，查找 endpoint 和 sessionId
            endpoint_url = None
            session_id = None
            
            try:
                for line in response.iter_lines(decode_unicode=True):
                    if not line:
                        continue
                    
                    # SSE 格式: event:endpoint 或 data:/path/to/endpoint?sessionId=xxx
                    if line.startswith('event:'):
                        event_type = line[6:].strip()
                        logger.debug(f"SSE 事件类型: {event_type}")
                    elif line.startswith('data:'):
                        data = line[5:].strip()
                        logger.debug(f"SSE 数据: {data}")
                        
                        # 解析 endpoint URL 和 sessionId
                        # 格式: /api/v1/mcps/WebSearch/message?sessionId=xxx
                        if data.startswith('/'):
                            # 提取 sessionId
                            if 'sessionId=' in data:
                                session_id = data.split('sessionId=')[1].split('&')[0]
                                # 构建完整的 endpoint URL
                                # data 格式: /api/v1/mcps/WebSearch/message?sessionId=xxx
                                # 需要提取路径部分并构建完整 URL
                                endpoint_path = data.split('?')[0]  # 只取路径部分
                                # 从 server.url 提取基础 URL
                                # server.url: https://dashscope.aliyuncs.com/api/v1/mcps/WebSearch/sse
                                # 需要去掉 /sse 后缀，然后加上 endpoint_path
                                base_url = server.url.rsplit('/sse', 1)[0]  # https://dashscope.aliyuncs.com/api/v1/mcps/WebSearch
                                # 如果 endpoint_path 已经是完整路径，直接使用
                                if endpoint_path.startswith('/api/'):
                                    # 从基础 URL 中提取域名部分
                                    from urllib.parse import urlparse
                                    parsed = urlparse(server.url)
                                    base_url = f"{parsed.scheme}://{parsed.netloc}"
                                endpoint_url = base_url + endpoint_path
                                logger.info(f"✅ 获取到 SSE endpoint: {endpoint_url}, sessionId: {session_id}")
                                break
            except Exception as e:
                logger.warning(f"解析 SSE 响应失败: {e}")
                self._set_default_server_info(server)
                return False
            
            if not endpoint_url or not session_id:
                logger.warning(f"SSE 连接未返回有效的 endpoint 或 sessionId")
                self._set_default_server_info(server)
                return False
            
            # 保存 sessionId 和 endpoint URL
            server.session_id = session_id
            # 将 endpoint URL 保存到 server 对象中（可能需要扩展 MCPServer 类）
            # 暂时保存到 server_info 中
            if not server.server_info:
                server.server_info = {}
            server.server_info['sse_endpoint'] = endpoint_url
            server.server_info['sse_base_url'] = server.url.rsplit('/sse', 1)[0]
            
            # 设置默认服务器信息
            if not server.name:
                server.name = server.id
            if not server.description:
                server.description = f"MCP服务器: {server.id}"
            
            logger.info(f"✅ SSE 服务器 {server.name} 会话初始化成功")
            return True
            
        except requests.exceptions.RequestException as e:
            logger.warning(f"SSE 连接失败: {e}")
            self._set_default_server_info(server)
            return False
        except Exception as e:
            logger.warning(f"初始化 SSE 服务器 {server.id} 时出错: {e}")
            self._set_default_server_info(server)
            return False
    
    def _set_default_server_info(self, server: MCPServer):
        """设置默认服务器信息（当initialize失败或不支持时）"""
        if not server.name:
            server.name = server.id
        if not server.description:
            server.description = f"MCP服务器: {server.id}"
        if not server.server_info:
            server.server_info = {}
    
    def _send_initialized_notification(self, server: MCPServer):
        """发送 initialized 通知（MCP协议要求）"""
        try:
            payload = {
                "jsonrpc": "2.0",
                "method": "notifications/initialized",
                "params": {}
            }
            
            headers = self._get_request_headers(server)
            
            response = requests.post(
                server.url.rstrip('/'),
                json=payload,
                headers=headers,
                timeout=5
            )
            # 通知通常返回 202 Accepted 或 200 OK
            if response.status_code in [200, 202]:
                logger.debug(f"✅ 服务器 {server.name} initialized 通知已发送")
            else:
                logger.warning(f"⚠️  服务器 {server.name} initialized 通知发送失败: HTTP {response.status_code}")
        except Exception as e:
            logger.warning(f"⚠️  发送 initialized 通知时出错: {e}")
    
    def _get_request_headers(self, server: MCPServer) -> Dict[str, str]:
        """获取请求头"""
        headers = {
            "Content-Type": "application/json"
        }
        
        # 添加配置中的headers
        if server.headers:
            headers.update(server.headers)
        
        # streamable_http和sse协议要求Accept头
        if server.type in ["streamable_http", "sse"]:
            headers["Accept"] = "application/json, text/event-stream"
        
        if server.requires_session and server.session_id:
            headers["mcp-session-id"] = server.session_id
        
        return headers

