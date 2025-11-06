"""
动态工具加载器
从MCP服务器发现工具并创建LangChain工具对象
"""

import logging
from typing import List, Dict, Any, Optional, TYPE_CHECKING
from langchain_core.tools import StructuredTool

# 兼容的 Pydantic 导入
try:
    # 尝试使用 LangChain 的 pydantic_v1（某些版本）
    from langchain_core.pydantic_v1 import BaseModel, Field
except ImportError:
    try:
        # 如果失败，尝试使用标准 pydantic
        from pydantic import BaseModel, Field
    except ImportError:
        # 如果还是失败，尝试使用 langchain 的其他导入方式
        try:
            from langchain.pydantic_v1 import BaseModel, Field
        except ImportError:
            # 最后的备选方案：直接使用 pydantic
            import pydantic
            BaseModel = pydantic.BaseModel
            Field = pydantic.Field

if TYPE_CHECKING:
    from mcp_server_manager import MCPServerManager, ToolInfo
else:
    from mcp_server_manager import MCPServerManager, ToolInfo

logger = logging.getLogger(__name__)


class MCPToolCaller:
    """MCP工具调用器"""
    
    def __init__(self, server_manager: MCPServerManager):
        self.server_manager = server_manager
    
    def call_tool(self, server_id: str, tool_name: str, arguments: Dict[str, Any]) -> str:
        """调用MCP服务器上的工具（自定义实现）"""
        import requests
        import json
        
        server = self.server_manager.servers.get(server_id)
        
        payload = {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "id": 1,
            "params": {
                "name": tool_name,
                "arguments": arguments
            }
        }
        
        try:
            # 获取请求头（可能包含session-id）
            headers = {"Content-Type": "application/json"}
            
            if server.requires_session:
                headers["Accept"] = "application/json, text/event-stream"
                if server.session_id:
                    headers["mcp-session-id"] = server.session_id
                else:
                    # 如果需要会话但没有session_id，尝试初始化
                    if hasattr(self.server_manager, '_init_server_session'):
                        self.server_manager._init_server_session(server)
                        if server.session_id:
                            headers["mcp-session-id"] = server.session_id
            
            # 对于 SSE 协议，使用返回的 endpoint URL
            if server.type == "sse" and server.server_info and server.server_info.get('sse_endpoint'):
                url = server.server_info['sse_endpoint']
                if server.session_id:
                    url = f"{url}?sessionId={server.session_id}"
                stream = True
            else:
                url = server.url.rstrip('/')
                stream = False
            
            logger.info(f"🔧 调用MCP工具: {url}, 工具: {tool_name}, 参数: {arguments}")
            logger.debug(f"🔧 请求payload: {json.dumps(payload, ensure_ascii=False, indent=2)}")
            logger.debug(f"🔧 请求headers: {headers}")
            
            response = requests.post(
                url,
                json=payload,
                headers=headers,
                timeout=30,
                stream=stream
            )
            
            logger.info(f"🔧 MCP响应: HTTP {response.status_code}")
            
            if response.status_code != 200:
                error_msg = f"HTTP {response.status_code}, 响应: {response.text[:200]}"
                logger.error(f"❌ MCP服务器返回错误状态码: {error_msg}")
                return f"错误: {error_msg}"
            
            try:
                # 对于 SSE 协议，需要解析事件流
                if server.type == "sse" and stream:
                    result_data = None
                    for line in response.iter_lines(decode_unicode=True):
                        if line and line.startswith('data:'):
                            json_str = line[5:].strip()  # 去掉 "data: " 前缀
                            try:
                                result_data = json.loads(json_str)
                                break  # 找到第一个有效响应
                            except json.JSONDecodeError:
                                continue
                    if result_data is None:
                        raise Exception("SSE 响应中未找到有效的 JSON 数据")
                else:
                    logger.debug(f"🔧 MCP响应内容: {response.text[:500]}")
                    result_data = response.json()
            except json.JSONDecodeError as e:
                error_msg = f"响应不是有效的JSON: {response.text[:200]}"
                logger.error(f"❌ MCP服务器响应解析失败: {error_msg}")
                return f"错误: {error_msg}"
            
            if "error" in result_data:
                error_info = result_data["error"]
                error_msg = f"{error_info.get('message', '未知错误')}"
                if error_info.get('data'):
                    error_msg += f", 详情: {error_info.get('data')}"
                logger.error(f"❌ MCP服务器返回错误: {error_msg}")
                return f"错误: {error_msg}"
            
            result = result_data.get("result", {})
            
            # 格式化结果
            if isinstance(result, dict):
                if "content" in result:
                    # 处理content数组（时间MCP服务器返回格式）
                    if isinstance(result["content"], list) and len(result["content"]) > 0:
                        content_text = result["content"][0].get("text", "")
                        try:
                            # 尝试解析JSON并格式化
                            content_data = json.loads(content_text)
                            return json.dumps(content_data, ensure_ascii=False, indent=2)
                        except json.JSONDecodeError:
                            # 如果不是JSON，直接返回文本
                            return content_text
                    # 如果content是字符串（文件操作MCP服务器返回格式）
                    elif isinstance(result["content"], str):
                        return f"文件内容 ({result.get('size', 0)} 字符):\n{result['content']}"
                    else:
                        # content为空或其他格式
                        return json.dumps(result, ensure_ascii=False, indent=2)
                elif "success" in result:
                    return result.get("message", "操作成功")
                elif "files" in result:
                    files = result.get("files", [])
                    dirs = result.get("directories", [])
                    file_list = "\n".join([f"- {f['name']} ({f['size']} bytes)" for f in files[:10]])
                    return f"目录: {result.get('path')}\n文件: {len(files)} 个, 目录: {len(dirs)} 个\n{file_list}"
                else:
                    # 其他格式，直接返回JSON
                    return json.dumps(result, ensure_ascii=False, indent=2)
            elif result is None:
                # result为None的情况
                logger.warning(f"⚠️  MCP服务器返回result为None")
                return "操作完成（无返回结果）"
            else:
                # result不是字典，直接转换为字符串
                return str(result)
        
        except requests.exceptions.ConnectionError:
            return f"错误: 无法连接到MCP服务器 {server.url}，请确保服务器正在运行"
        except Exception as e:
            return f"错误: {str(e)}"


def create_dynamic_tool(tool_info: ToolInfo, caller: MCPToolCaller) -> StructuredTool:
    """
    为MCP工具创建LangChain工具对象
    
    Args:
        tool_info: 工具信息
        caller: MCP工具调用器
    
    Returns:
        LangChain工具对象
    """
    # 构建增强的工具描述（帮助LLM更好理解）
    description_parts = [f"[{tool_info.server_id}] {tool_info.description}"]
    
    if tool_info.category:
        description_parts.append(f"类别: {tool_info.category}")
    
    # 添加参数说明（帮助LLM理解参数）
    parameters = tool_info.parameters
    properties = parameters.get("properties", {})
    required = parameters.get("required", [])
    
    if properties:
        description_parts.append("\n参数:")
        for param_name, param_info in properties.items():
            param_type = param_info.get("type", "unknown")
            param_desc = param_info.get("description", "")
            is_required = param_name in required
            
            param_line = f"  - {param_name} ({param_type})"
            if is_required:
                param_line += " [必需]"
            else:
                param_line += " [可选]"
            if param_desc:
                param_line += f": {param_desc}"
            description_parts.append(param_line)
    
    # 添加使用提示
    if required:
        required_params = ", ".join([f'"{p}"' for p in required])
        description_parts.append(f"\n提示: 调用此工具时，必须提供以下参数: {required_params}")
    
    description = "\n".join(description_parts)
    
    # 创建动态参数模型（使用已获取的 parameters）
    
    # 动态创建Pydantic模型
    field_definitions = {}
    for param_name, param_info in properties.items():
        param_type = param_info.get("type", "string")
        param_desc = param_info.get("description", "")
        param_default = param_info.get("default")
        
        # 映射JSON Schema类型到Python类型
        if param_type == "string":
            field_type = str
        elif param_type == "integer":
            field_type = int
        elif param_type == "number":
            field_type = float
        elif param_type == "boolean":
            field_type = bool
        elif param_type == "array":
            field_type = List
        elif param_type == "object":
            field_type = Dict[str, Any]
        else:
            field_type = Any
        
        # 创建字段
        field_kwargs = {"description": param_desc}
        if param_name not in required:
            field_kwargs["default"] = param_default if param_default is not None else None
        
        field_definitions[param_name] = (field_type, Field(**field_kwargs))
    
    # 创建动态模型类
    if field_definitions:
        ToolInputModel = type(
            f"{tool_info.server_id}_{tool_info.name}_Input",
            (BaseModel,),
            {
                "__annotations__": {k: v[0] for k, v in field_definitions.items()},
                **{k: v[1] for k, v in field_definitions.items()}
            }
        )
    else:
        ToolInputModel = None
    
    # 创建工具函数
    def tool_function(**kwargs):
        return caller.call_tool(tool_info.server_id, tool_info.name, kwargs)
    
    # 创建工具名称（格式：server_id_tool_name）
    tool_name = f"{tool_info.server_id}_{tool_info.name}"
    
    # 创建LangChain工具
    try:
        if ToolInputModel:
            langchain_tool = StructuredTool.from_function(
                func=tool_function,
                name=tool_name,
                description=description,
                args_schema=ToolInputModel
            )
        else:
            # 没有参数的工具
            langchain_tool = StructuredTool.from_function(
                func=tool_function,
                name=tool_name,
                description=description
            )
        
        return langchain_tool
    except Exception as e:
        logger.error(f"创建工具 {tool_name} 失败: {e}")
        # 如果创建失败，创建一个简单的工具
        return StructuredTool.from_function(
            func=tool_function,
            name=tool_name,
            description=description
        )


def load_dynamic_tools(server_manager: MCPServerManager, force_refresh: bool = False) -> List[StructuredTool]:
    """
    从MCP服务器加载所有工具
    
    Args:
        server_manager: MCP服务器管理器
        force_refresh: 是否强制刷新
    
    Returns:
        LangChain工具列表
    """
    # 发现所有工具
    all_tools_info = server_manager.get_all_tools(force_refresh=force_refresh)
    
    # 创建调用器
    caller = MCPToolCaller(server_manager)
    
    # 为每个工具创建LangChain工具对象
    langchain_tools = []
    for tool_info in all_tools_info:
        try:
            langchain_tool = create_dynamic_tool(tool_info, caller)
            langchain_tools.append(langchain_tool)
            logger.info(f"✅ 加载工具: {tool_info.server_id}.{tool_info.name}")
        except Exception as e:
            logger.error(f"❌ 加载工具失败 {tool_info.server_id}.{tool_info.name}: {e}")
    
    logger.info(f"✅ 总共加载了 {len(langchain_tools)} 个动态工具")
    return langchain_tools


def load_tools_by_retrieval(retrieval_manager, query: str, top_k: int = 3, 
                           server_manager: MCPServerManager = None) -> List[StructuredTool]:
    """
    通过检索管理器按需加载工具（用于减少token使用）
    
    Args:
        retrieval_manager: 工具检索管理器
        query: 查询文本（AI的需求描述）
        top_k: 返回最匹配的工具数量
        server_manager: MCP服务器管理器（用于创建工具调用器）
    
    Returns:
        LangChain工具列表（只包含匹配的工具）
    """
    if server_manager is None:
        server_manager = retrieval_manager.server_manager
    
    # 搜索匹配的工具
    matched_tools_info = retrieval_manager.search_tools(query, top_k=top_k)
    
    if not matched_tools_info:
        logger.warning(f"未找到匹配的工具: {query}")
        return []
    
    # 创建调用器
    caller = MCPToolCaller(server_manager)
    
    # 为匹配的工具创建LangChain工具对象
    langchain_tools = []
    for tool_info in matched_tools_info:
        try:
            langchain_tool = create_dynamic_tool(tool_info, caller)
            langchain_tools.append(langchain_tool)
            logger.info(f"✅ 检索并加载工具: {tool_info.server_id}.{tool_info.name}")
        except Exception as e:
            logger.error(f"❌ 加载工具失败 {tool_info.server_id}.{tool_info.name}: {e}")
    
    logger.info(f"✅ 检索到 {len(langchain_tools)} 个匹配的工具")
    return langchain_tools
