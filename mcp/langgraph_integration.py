"""
LangGraph集成示例
演示如何从LangGraph Agent调用MCP服务器（动态工具加载版本）
"""

import os
import logging
from dotenv import load_dotenv
from typing import TypedDict, Annotated, Sequence, Dict, List, Optional, Any
import operator

from langchain_openai import ChatOpenAI
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage
from langchain_core.tools import StructuredTool
from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode

# 导入动态工具加载模块
from mcp_server_manager import MCPServerManager
from dynamic_tool_loader import load_dynamic_tools, load_tools_by_retrieval
from tool_retrieval_manager import ToolRetrievalManager

# 加载环境变量
load_dotenv()

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 忽略 isAlive() 弃用警告（来自依赖库，等待库更新）
import warnings
warnings.filterwarnings("ignore", message=".*isAlive.*", category=DeprecationWarning)


# ========== 定义状态 ==========

class AgentState(TypedDict):
    """Agent状态定义"""
    messages: Annotated[Sequence[BaseMessage], operator.add]
    """消息列表"""


# ========== 定义节点 ==========

def _format_tool_parameters(parameters: Dict[str, Any]) -> str:
    """格式化工具参数为简洁的描述"""
    if not parameters:
        return "无参数"
    
    props = parameters.get("properties", {})
    required = parameters.get("required", [])
    
    if not props:
        return "无参数"
    
    param_descs = []
    for param_name, param_info in props.items():
        param_type = param_info.get("type", "unknown")
        param_desc = param_info.get("description", "")
        is_required = param_name in required
        
        # 简化参数描述
        if param_desc:
            param_desc_short = param_desc[:40] + "..." if len(param_desc) > 40 else param_desc
            param_str = f"{param_name} ({param_type}): {param_desc_short}"
        else:
            param_str = f"{param_name} ({param_type})"
        
        if is_required:
            param_str += " [必需]"
        else:
            param_str += " [可选]"
        
        param_descs.append(param_str)
    
    return "; ".join(param_descs[:3])  # 最多显示3个参数


def _generate_mcp_server_catalog(server_manager: MCPServerManager) -> str:
    """
    生成MCP服务器目录（只包含服务器和功能概述，不包含详细工具信息）
    用于存放到上下文中，让AI了解有哪些MCP服务器可用
    
    Args:
        server_manager: MCP服务器管理器
        
    Returns:
        服务器目录文本（简化版，只包含功能概述）
    """
    descriptions = ["你是一个AI助手，可以通过调用多个MCP服务器来完成各种任务。\n"]
    descriptions.append(f"当前有 {len(server_manager.servers)} 个MCP服务器可用：\n")
    
    # 发现所有工具（使用缓存，不强制刷新）用于生成功能概述
    all_tools = server_manager.discover_tools(force_refresh=False)
    
    for server_id, server in server_manager.servers.items():
        if not server.enabled:
            continue
        
        server_info = f"\n{server.name or server_id} ({server_id}):"
        if server.description:
            server_info += f"\n  描述: {server.description}"
        if server.category:
            server_info += f"\n  类别: {server.category}"
        
        # 只添加功能概述，不包含详细工具信息
        if server_id in all_tools:
            tools = all_tools[server_id]
            if tools:
                # 提取工具功能关键词（从工具描述中提取核心功能）
                tool_capabilities = []
                for tool_info in tools:
                    # 从工具描述中提取核心功能词
                    desc = tool_info.description.lower()
                    name = tool_info.name.lower()
                    
                    # 匹配常见功能关键词
                    if any(kw in desc or kw in name for kw in ["read", "读取", "read_file"]):
                        if "读取" not in tool_capabilities and "读取文件" not in tool_capabilities:
                            tool_capabilities.append("读取文件")
                    elif any(kw in desc or kw in name for kw in ["write", "写入", "write_file"]):
                        if "写入" not in tool_capabilities and "写入文件" not in tool_capabilities:
                            tool_capabilities.append("写入文件")
                    elif any(kw in desc or kw in name for kw in ["list", "列出", "list_files"]):
                        if "列出" not in tool_capabilities and "列出文件" not in tool_capabilities:
                            tool_capabilities.append("列出文件")
                    elif any(kw in desc or kw in name for kw in ["query", "查询", "execute_query"]):
                        if "查询" not in tool_capabilities and "查询数据" not in tool_capabilities:
                            tool_capabilities.append("查询数据")
                    elif any(kw in desc or kw in name for kw in ["time", "时间", "get_time"]):
                        if "获取时间" not in tool_capabilities:
                            tool_capabilities.append("获取时间")
                    elif any(kw in desc or kw in name for kw in ["execute", "执行", "update"]):
                        if "执行操作" not in tool_capabilities:
                            tool_capabilities.append("执行操作")
                    elif any(kw in desc or kw in name for kw in ["train", "火车", "车次", "12306"]):
                        if "查询车次" not in tool_capabilities:
                            tool_capabilities.append("查询车次")
                
                # 如果没匹配到，使用工具名称的简化版本
                if not tool_capabilities:
                    for tool_info in tools[:3]:  # 最多显示3个工具名称
                        tool_capabilities.append(tool_info.name)
                
                # 去重并限制数量
                unique_capabilities = list(dict.fromkeys(tool_capabilities))[:5]
                if unique_capabilities:
                    server_info += f"\n  功能: {', '.join(unique_capabilities)}"
        
        descriptions.append(server_info)
    
    descriptions.append("\n" + "="*60)
    descriptions.append("使用说明：")
    descriptions.append("1. 当你需要使用某个MCP服务器时，先使用 'get_mcp_server_tools' 工具查询该服务器的完整工具信息")
    descriptions.append("2. 查询格式：get_mcp_server_tools(server_id='服务器ID')")
    descriptions.append("3. 查询到完整工具信息后，可以使用相应的工具完成操作")
    descriptions.append("4. 工具调用格式：server_id_tool_name(参数)")
    descriptions.append("5. 可以在一次对话中调用多个不同MCP服务器的工具完成复杂任务")
    descriptions.append("="*60)
    
    return "\n".join(descriptions)


def _generate_tools_description(tools_list: List[StructuredTool], server_manager: MCPServerManager) -> str:
    """动态生成工具描述文本（用于已查询到的工具）"""
    # 按服务器分组工具
    tools_by_server: Dict[str, List[StructuredTool]] = {}
    for tool in tools_list:
        # 工具名称格式：server_id_tool_name
        parts = tool.name.split('_', 1)
        if len(parts) == 2:
            server_id = parts[0]
            if server_id not in tools_by_server:
                tools_by_server[server_id] = []
            tools_by_server[server_id].append(tool)
    
    descriptions = ["已查询到的工具：\n"]
    
    for server_id, server_tools in tools_by_server.items():
        server = server_manager.servers.get(server_id)
        if server:
            descriptions.append(f"\n{server.name} ({server_id}):")
            descriptions.append("可用工具:")
            for tool in server_tools:
                tool_name = tool.name.split('_', 1)[1] if '_' in tool.name else tool.name
                descriptions.append(f"  - {tool.name}: {tool.description}")
        else:
            descriptions.append(f"\n未知服务器 ({server_id}):")
            for tool in server_tools:
                descriptions.append(f"  - {tool.name}: {tool.description}")
    
    descriptions.append("\n调用工具时，请使用工具的全名（格式：server_id_tool_name），并提供正确的参数。")
    
    return "\n".join(descriptions)


def _extract_tool_requirements(llm, user_message: str, conversation_context: List[BaseMessage] = None) -> Optional[str]:
    """
    使用LLM判断是否需要工具并提炼功能需求（优化版本）
    
    优化点：
    1. 使用更精简的prompt减少token消耗
    2. 结合对话上下文理解指代
    3. 合并判断和提炼到一个调用中
    
    Args:
        llm: LLM实例
        user_message: 用户原始消息
        conversation_context: 对话上下文（可选）
        
    Returns:
        提炼后的功能需求描述，如果不需要工具则返回 None
    """
    try:
        # 构建上下文信息（如果有）
        context_hint = ""
        if conversation_context:
            # 只使用最近的几条消息作为上下文
            recent_messages = conversation_context[-3:] if len(conversation_context) > 3 else conversation_context
            context_texts = []
            for msg in recent_messages:
                if hasattr(msg, 'content'):
                    content = str(msg.content)[:100]  # 限制长度
                    context_texts.append(content)
            if context_texts:
                context_hint = f"\n对话上下文：{' '.join(context_texts)}"
        
        # 优化的精简prompt（减少token）
        prompt = f"""分析用户需求，判断是否需要工具。如果只是问候/感谢/确认，返回"无需工具"；如果需要工具，返回功能描述（如：读取文件、查询数据库）。

用户需求：{user_message}{context_hint}

返回（仅返回判断结果或功能描述，无需解释）："""
        
        # 使用精简的system message
        messages = [
            SystemMessage(content="判断用户是否需要工具，如果需要则返回功能描述，否则返回'无需工具'。"),
            HumanMessage(content=prompt)
        ]
        
        response = llm.invoke(messages)
        refined_query = response.content.strip()
        
        # 判断结果
        no_tool_keywords = ["无需工具", "不需要工具", "无工具需求", "无需", "no tool", "no need"]
        if any(keyword in refined_query.lower() for keyword in no_tool_keywords):
            logger.debug(f"LLM判断不需要工具: {user_message[:50]}")
            return None
        
        # 如果返回为空或太短，可能不需要工具
        if len(refined_query) < 2:
            logger.debug(f"LLM返回空，可能不需要工具: {user_message[:50]}")
            return None
        
        logger.info(f"📝 需求提炼: {user_message[:50]}... → {refined_query}")
        return refined_query
    
    except Exception as e:
        logger.warning(f"⚠️  需求提炼失败，使用原始消息: {str(e)}")
        return user_message




def create_get_mcp_tools_tool(server_manager: MCPServerManager, retrieval_manager: Optional[ToolRetrievalManager] = None):
    """
    创建查询MCP服务器工具列表的工具
    让AI可以查询指定MCP服务器的完整工具信息（从MongoDB或server_manager）
    """
    from langchain_core.tools import tool
    
    @tool
    def get_mcp_server_tools(server_id: str) -> str:
        """
        查询指定MCP服务器的完整工具信息（包括工具名称、描述、参数等）
        
        Args:
            server_id: MCP服务器的ID（如：file_server, time_server, mysql_server等）
        
        Returns:
            该服务器的完整工具信息（JSON格式）
        """
        import json
        
        # 检查服务器是否存在
        if server_id not in server_manager.servers:
            available_servers = ", ".join(server_manager.servers.keys())
            return f"错误：服务器 {server_id} 不存在。可用的服务器：{available_servers}"
        
        server = server_manager.servers[server_id]
        if not server.enabled:
            return f"错误：服务器 {server_id} 已禁用"
        
        # 优先从MongoDB获取（如果可用）
        tools_info_list = []
        if retrieval_manager:
            try:
                mongo_tools = retrieval_manager.mongo_client.get_tools_by_server(server_id)
                if mongo_tools:
                    # 从MongoDB文档构建工具信息
                    for mongo_tool in mongo_tools:
                        tool_data = {
                            "name": mongo_tool.get("tool_name", ""),
                            "description": mongo_tool.get("tool_description", ""),
                            "parameters": mongo_tool.get("tool_parameters", {})
                        }
                        tools_info_list.append(tool_data)
                    logger.info(f"✅ 从MongoDB查询到服务器 {server_id} 的 {len(tools_info_list)} 个工具")
            except Exception as e:
                logger.warning(f"⚠️  从MongoDB查询失败，使用server_manager: {e}")
        
        # 如果MongoDB没有数据，从server_manager获取
        if not tools_info_list:
            try:
                tools = server_manager.discover_tools(server_id=server_id, force_refresh=False)
                if not tools or server_id not in tools:
                    return f"错误：无法获取服务器 {server_id} 的工具列表，请检查服务器是否运行"
                
                tool_list = tools[server_id]
                
                for tool_info in tool_list:
                    tool_data = {
                        "name": tool_info.name,
                        "description": tool_info.description,
                        "parameters": tool_info.parameters
                    }
                    tools_info_list.append(tool_data)
                
                logger.info(f"✅ 从server_manager查询到服务器 {server_id} 的 {len(tools_info_list)} 个工具")
            except Exception as e:
                logger.error(f"❌ 查询服务器 {server_id} 工具失败: {str(e)}")
                return f"错误：查询服务器 {server_id} 的工具列表失败: {str(e)}"
        
        # 构建返回结果
        result = {
            "server_id": server_id,
            "server_name": server.name or server_id,
            "server_description": server.description or "",
            "tools": tools_info_list
        }
        
        return json.dumps(result, ensure_ascii=False, indent=2)
    
    return get_mcp_server_tools


def create_chat_node(llm, retrieval_manager: Optional[ToolRetrievalManager], 
                    server_manager: MCPServerManager, use_catalog: bool = True):
    """
    创建Chat节点（使用MCP服务器目录模式，只包含功能概述）
    
    Args:
        llm: LLM实例
        retrieval_manager: 工具检索管理器（用于从MongoDB查询工具信息）
        server_manager: MCP服务器管理器
        use_catalog: 是否使用目录模式（True：目录模式，False：传统模式）
    """
    
    # 生成MCP服务器目录（只包含功能概述）
    mcp_catalog = _generate_mcp_server_catalog(server_manager)
    
    # 创建查询工具
    get_mcp_tools_tool = create_get_mcp_tools_tool(server_manager, retrieval_manager)
    
    # 用于跟踪已查询并加载的工具（按服务器ID）
    loaded_tools_cache: Dict[str, List[StructuredTool]] = {}
    
    def chat_node(state: AgentState):
        """Chat节点：处理对话，决定下一步行动"""
        messages = state["messages"]
        
        # 从消息历史中收集已查询的MCP服务器ID
        queried_servers = set()
        for msg in messages:
            if hasattr(msg, 'tool_calls') and msg.tool_calls:
                for tool_call in msg.tool_calls:
                    if tool_call.get("name") == "get_mcp_server_tools":
                        args = tool_call.get("args", {})
                        server_id = args.get("server_id")
                        if server_id:
                            queried_servers.add(server_id)
            
            # 检查ToolMessage（查询工具的返回结果）
            if hasattr(msg, 'content') and hasattr(msg, 'name') and msg.name == "get_mcp_server_tools":
                # 尝试从返回结果中提取server_id
                try:
                    import json
                    content = msg.content
                    if isinstance(content, str):
                        result = json.loads(content)
                        server_id = result.get("server_id")
                        if server_id:
                            queried_servers.add(server_id)
                except:
                    pass
        
        # 加载已查询的MCP服务器的工具
        tools_list = []
        for server_id in queried_servers:
            if server_id in loaded_tools_cache:
                tools_list.extend(loaded_tools_cache[server_id])
            else:
                # 动态加载该服务器的工具
                try:
                    server_tools_info = server_manager.discover_tools(server_id=server_id, force_refresh=False)
                    if server_id in server_tools_info:
                        from dynamic_tool_loader import create_dynamic_tool, MCPToolCaller
                        caller = MCPToolCaller(server_manager)
                        
                        server_tools = []
                        for tool_info in server_tools_info[server_id]:
                            try:
                                langchain_tool = create_dynamic_tool(tool_info, caller)
                                server_tools.append(langchain_tool)
                            except Exception as e:
                                logger.error(f"❌ 加载工具失败 {server_id}.{tool_info.name}: {e}")
                        
                        loaded_tools_cache[server_id] = server_tools
                        tools_list.extend(server_tools)
                        logger.info(f"✅ 已加载服务器 {server_id} 的 {len(server_tools)} 个工具")
                except Exception as e:
                    logger.error(f"❌ 加载服务器 {server_id} 的工具失败: {e}")
        
        # 检查消息历史中是否有错误（避免无限循环）
        from langchain_core.messages import ToolMessage
        error_messages = [msg for msg in messages if isinstance(msg, ToolMessage) and 
                         isinstance(msg.content, str) and 
                         ("错误" in msg.content or "失败" in msg.content or "抱歉" in msg.content)]
        
        # 构建系统消息
        if use_catalog:
            # 使用目录模式：包含MCP服务器目录 + 已查询的工具详细描述
            if tools_list:
                tools_description = _generate_tools_description(tools_list, server_manager)
                system_content = mcp_catalog + "\n\n" + tools_description
            else:
                system_content = mcp_catalog
        else:
            # 传统模式：只包含已加载的工具
            if tools_list:
                tools_description = _generate_tools_description(tools_list, server_manager)
                system_content = tools_description
            else:
                system_content = "你是一个AI助手。当前没有可用的工具。"
        
        # 如果最近有错误消息，在系统消息中添加提示，让LLM直接回复用户而不是继续调用工具
        if error_messages:
            error_hint = "\n\n⚠️ 重要提示：最近的工具调用出现了错误。请向用户友好地说明错误情况，不要继续尝试调用工具。直接回复用户即可。"
            system_content = system_content + error_hint
        
        system_message = SystemMessage(content=system_content)
        agent_messages = [system_message] + list(messages)
        
        # 绑定工具：查询工具 + 已加载的MCP工具
        tools_to_bind = [get_mcp_tools_tool] + tools_list
        
        # 调试日志：显示绑定的工具
        if tools_list:
            logger.info(f"🔧 绑定 {len(tools_list)} 个MCP工具: {[tool.name for tool in tools_list]}")
        else:
            logger.debug("🔧 当前没有已加载的MCP工具，只有查询工具")
        
        # 如果有错误消息，不绑定工具，让LLM直接回复
        if error_messages:
            logger.info("⚠️  检测到错误消息，不绑定工具，让LLM直接回复用户")
            llm_with_tools = llm
        elif tools_to_bind:
            llm_with_tools = llm.bind_tools(tools_to_bind)
        else:
            llm_with_tools = llm
        
        # 调用LLM
        response = llm_with_tools.invoke(agent_messages)
        
        # 调试日志：检查LLM响应
        if hasattr(response, 'tool_calls') and response.tool_calls:
            logger.info(f"🔧 LLM生成了 {len(response.tool_calls)} 个工具调用:")
            for tool_call in response.tool_calls:
                logger.info(f"   - {tool_call.get('name')}({tool_call.get('args')})")
        else:
            content_preview = response.content[:100] if hasattr(response, 'content') and response.content else 'N/A'
            logger.debug(f"💬 LLM返回文本响应: {content_preview}")
        
        return {"messages": [response]}
    
    return chat_node


def create_tool_node(retrieval_manager: Optional[ToolRetrievalManager], server_manager: MCPServerManager):
    """创建动态工具节点（根据工具调用动态加载工具）"""
    from langchain_core.messages import ToolMessage
    from dynamic_tool_loader import MCPToolCaller
    
    # 创建查询工具实例（用于执行查询工具调用）
    get_mcp_tools_tool = create_get_mcp_tools_tool(server_manager, retrieval_manager)
    
    def tool_node(state: AgentState):
        """工具节点：执行工具调用"""
        messages = state["messages"]
        last_message = messages[-1]
        
        tool_calls = getattr(last_message, 'tool_calls', None) or []
        if not tool_calls:
            return {"messages": []}
        
        # 创建MCP工具调用器
        caller = MCPToolCaller(server_manager)
        
        tool_messages = []
        logger.info(f"🔧 Tool节点收到 {len(tool_calls)} 个工具调用")
        for tool_call in tool_calls:
            tool_name = tool_call.get("name", "")
            tool_args = tool_call.get("args", {})
            tool_call_id = tool_call.get("id", "")
            
            logger.info(f"🔧 处理工具调用: {tool_name}({tool_args})")
            
            # 处理查询工具调用
            if tool_name == "get_mcp_server_tools":
                try:
                    result = get_mcp_tools_tool.invoke(tool_args)
                    tool_messages.append(
                        ToolMessage(content=result, tool_call_id=tool_call_id)
                    )
                except Exception as e:
                    error_msg = str(e)
                    logger.error(f"❌ 执行查询工具失败: {error_msg}")
                    friendly_error = f"抱歉，查询MCP服务器工具信息时发生错误：{error_msg}。请检查服务器ID是否正确，或稍后重试。"
                    tool_messages.append(
                        ToolMessage(content=f"错误: {friendly_error}", tool_call_id=tool_call_id)
                    )
                continue
            
            # 处理MCP工具调用（格式：server_id_tool_name）
            # 注意：server_id可能包含下划线（如time_server），需要匹配最长的server_id
            server_id = None
            actual_tool_name = None
            
            # 按长度降序排序server_id，优先匹配最长的（避免time_server被分割成time）
            sorted_server_ids = sorted(server_manager.servers.keys(), key=len, reverse=True)
            
            for sid in sorted_server_ids:
                if tool_name.startswith(sid + '_'):
                    server_id = sid
                    actual_tool_name = tool_name[len(sid) + 1:]  # 去掉 server_id_ 前缀
                    break
            
            if server_id and actual_tool_name:
                logger.info(f"🔧 解析工具: server_id={server_id}, tool_name={actual_tool_name}")
                try:
                    # 调用工具
                    result = caller.call_tool(server_id, actual_tool_name, tool_args)
                    logger.info(f"✅ 工具调用成功: {tool_name}")
                    tool_messages.append(
                        ToolMessage(content=result, tool_call_id=tool_call_id)
                    )
                except Exception as e:
                    error_msg = str(e)
                    logger.error(f"❌ 调用工具失败 {tool_name}: {error_msg}", exc_info=True)
                    # 返回友好的错误信息
                    friendly_error = f"抱歉，调用工具 {tool_name} 时发生错误：{error_msg}。请检查工具参数是否正确，或稍后重试。"
                    tool_messages.append(
                        ToolMessage(content=f"错误: {friendly_error}", tool_call_id=tool_call_id)
                    )
            else:
                logger.warning(f"⚠️  无法解析工具名称: {tool_name}，格式应为 server_id_tool_name")
                available_servers = ", ".join(server_manager.servers.keys())
                friendly_error = f"无法识别工具名称 {tool_name}。工具名称格式应为 server_id_tool_name（例如：file_server_read_file）。可用的服务器ID：{available_servers}"
                tool_messages.append(
                    ToolMessage(content=f"错误: {friendly_error}", tool_call_id=tool_call_id)
                )
        
        return {"messages": tool_messages}
    
    return tool_node


def should_continue(state: AgentState):
    """判断是否继续执行工具"""
    messages = state["messages"]
    if not messages:
        return END
    
    last_message = messages[-1]
    
    # 检查是否有工具调用
    tool_calls = getattr(last_message, 'tool_calls', None) or []
    if tool_calls:
        return "tools"
    
    # 检查是否是工具执行结果
    from langchain_core.messages import ToolMessage
    if isinstance(last_message, ToolMessage):
        # 检查工具执行是否失败（包含错误信息）
        content = last_message.content
        if isinstance(content, str):
            # 如果工具返回错误信息，返回chat让LLM处理错误并回复用户
            if content.startswith("错误:") or "错误" in content or "失败" in content or "抱歉" in content:
                logger.warning(f"⚠️  工具执行失败，让LLM处理错误并回复用户: {content[:100]}")
                # 检查是否已经有多次错误，如果是则直接结束
                error_count = sum(1 for msg in messages if isinstance(msg, ToolMessage) and 
                                 isinstance(msg.content, str) and 
                                 ("错误" in msg.content or "失败" in msg.content or "抱歉" in msg.content))
                if error_count >= 3:  # 如果连续3次错误，直接结束
                    logger.warning("⚠️  工具调用连续失败多次，结束调用")
                    return END
                return "chat"  # 返回chat让LLM处理错误并回复用户
        
        # 工具执行完成，返回chat节点处理结果
        tool_message_count = sum(1 for msg in messages if isinstance(msg, ToolMessage))
        if tool_message_count >= 10:  # 最多执行10次工具调用
            logger.warning("⚠️  工具调用次数过多，结束调用")
            return END
        return "chat"
    
    return END


# ========== 构建图 ==========

def create_agent_graph(config_path: str = "mcp_servers.json", use_retrieval: bool = True):
    """创建Agent状态图（使用工具检索管理器）"""
    # 初始化LLM
    api_key = os.getenv("AI_DASHSCOPE_API_KEY", "")
    if not api_key:
        raise ValueError("请设置环境变量 AI_DASHSCOPE_API_KEY")
    
    llm = ChatOpenAI(
        openai_api_key=api_key,
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        model="qwen-max",
        temperature=0.7
    )
    
    # 初始化MCP服务器管理器
    logger.info("📋 初始化MCP服务器管理器...")
    server_manager = MCPServerManager(config_path)
    
    # 初始化工具检索管理器（用于从MongoDB查询工具信息）
    logger.info("🔍 初始化工具检索管理器...")
    retrieval_manager = None
    try:
        retrieval_manager = ToolRetrievalManager(
            server_manager=server_manager,
            mongo_host="localhost",
            mongo_port=27017,
            refresh_interval=600
        )
        
        # 清空并重建索引（以配置文件为准）
        logger.info("📊 准备构建工具索引...")
        logger.info("清空现有索引数据...")
        retrieval_manager.mongo_client.clear_index()
        
        logger.info("开始构建索引（基于当前配置文件）...")
        indexed_count = retrieval_manager.build_index()
        logger.info(f"✅ 索引构建完成: {indexed_count} 个工具已索引")
        
        # 启动自动刷新
        retrieval_manager.start_auto_refresh()
        
    except Exception as e:
        logger.error(f"初始化工具检索管理器失败: {str(e)}")
        logger.warning("将使用server_manager直接查询工具信息")
        retrieval_manager = None
    
    # 创建节点（使用目录模式，只包含功能概述）
    logger.info("📋 使用MCP服务器目录模式：目录中只包含功能概述，完整工具信息存储在MongoDB中")
    logger.info("📋 AI需要调用工具时，先使用get_mcp_server_tools查询完整信息，再进行调用")
    chat_node = create_chat_node(llm, retrieval_manager, server_manager, use_catalog=True)
    tool_node = create_tool_node(retrieval_manager, server_manager)
    
    # 创建状态图
    workflow = StateGraph(AgentState)
    
    # 添加节点
    workflow.add_node("chat", chat_node)
    workflow.add_node("tools", tool_node)
    
    # 设置入口点
    workflow.set_entry_point("chat")
    
    # 添加条件边
    workflow.add_conditional_edges(
        "chat",
        should_continue,
        {
            "tools": "tools",
            END: END
        }
    )
    
    workflow.add_conditional_edges(
        "tools",
        should_continue,
        {
            "chat": "chat",
            END: END
        }
    )
    
    return workflow.compile()


# ========== 主程序 ==========

def main():
    """主程序"""
    print("=" * 60)
    print("🤖 LangGraph Agent with MCP Server")
    print("=" * 60)
    print("💡 提示：输入 'exit' 或 'quit' 退出程序")
    print("=" * 60)
    
    # 检查MCP服务器（使用服务器管理器）
    print("📋 检查MCP服务器状态...")
    server_manager = MCPServerManager("mcp_servers.json")
    
    available_servers = 0
    for server_id, server in server_manager.servers.items():
        if server.enabled:
            is_healthy = server_manager.check_server_health(server_id)
            if is_healthy:
                print(f"✅ {server.name} ({server_id}) - {server.url}")
                available_servers += 1
            else:
                print(f"❌ {server.name} ({server_id}) - {server.url} (无法连接)")
                print(f"   请确保服务器正在运行")
        else:
            print(f"⏸️  {server.name} ({server_id}) - 已禁用")
    
    print()
    
    if available_servers == 0:
        print("⚠️  警告: 没有可用的MCP服务器，部分功能可能无法使用\n")
    elif available_servers < len(server_manager.servers):
        print(f"⚠️  警告: {len(server_manager.servers) - available_servers} 个MCP服务器不可用，部分功能可能受限\n")
    
    # 创建Agent图
    print("🚀 初始化LangGraph Agent...")
    app = create_agent_graph()
    print("✅ Agent初始化完成\n")
    
    # 初始消息：让AI根据MCP服务器目录介绍可用功能
    initial_prompt = "你好！请根据当前可用的MCP服务器，向用户介绍你可以帮助他们完成哪些任务。只介绍实际可用的功能，不要编造。"
    initial_state: AgentState = {
        "messages": [HumanMessage(content=initial_prompt)],
    }
    
    # 运行一次Agent，让AI生成介绍
    print("🤖 助手: ", end="", flush=True)
    try:
        result = app.invoke(initial_state, config={"recursion_limit": 10})
        if "messages" in result:
            last_message = result["messages"][-1]
            if isinstance(last_message, AIMessage) and last_message.content:
                print(last_message.content)
            else:
                print("你好！我可以帮你完成多种任务。")
        else:
            print("你好！我可以帮你完成多种任务。")
    except Exception as e:
        logger.error(f"生成初始介绍失败: {e}")
        print("你好！我可以帮你完成多种任务。")
    
    print()
    
    while True:
        try:
            # 获取用户输入
            user_input = input("👤 您: ").strip()
            
            if user_input.lower() in ['exit', 'quit', '退出']:
                print("\n👋 再见！感谢使用！")
                break
            
            if not user_input:
                print("⚠️ 请输入有效的问题")
                continue
            
            # 添加用户消息
            initial_state["messages"].append(HumanMessage(content=user_input))
            
            # 运行图
            print("\n🔄 助手正在思考...")
            result = app.invoke(initial_state, config={"recursion_limit": 50})
            
            # 显示回复
            if "messages" in result:
                last_message = result["messages"][-1]
                if isinstance(last_message, AIMessage) and last_message.content:
                    print(f"🤖 助手: {last_message.content}\n")
            
            # 更新状态
            initial_state = result
        
        except KeyboardInterrupt:
            print("\n\n👋 程序被中断，再见！")
            break
        except Exception as e:
            print(f"\n❌ 发生错误: {str(e)}")
            print("请检查网络连接和配置")


if __name__ == "__main__":
    main()

