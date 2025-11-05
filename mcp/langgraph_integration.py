"""
LangGraph集成示例
演示如何从LangGraph Agent调用MCP服务器（动态工具加载版本）
"""

import os
import logging
from dotenv import load_dotenv
from typing import TypedDict, Annotated, Sequence, Dict, List
import operator

from langchain_openai import ChatOpenAI
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage
from langchain_core.tools import StructuredTool
from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode

# 导入动态工具加载模块
from mcp_server_manager import MCPServerManager
from dynamic_tool_loader import load_dynamic_tools

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

def _generate_tools_description(tools_list: List[StructuredTool], server_manager: MCPServerManager) -> str:
    """动态生成工具描述文本"""
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
    
    descriptions = ["你是一个AI助手，可以通过调用多个MCP服务器来完成各种任务。\n"]
    descriptions.append(f"当前有 {len(server_manager.servers)} 个MCP服务器可用：\n")
    
    for server_id, server_tools in tools_by_server.items():
        server = server_manager.servers.get(server_id)
        if server:
            descriptions.append(f"\n{server.name} ({server_id}):")
            descriptions.append(f"描述: {server.description}")
            if server.category:
                descriptions.append(f"类别: {server.category}")
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


def create_chat_node(llm, tools_list: List[StructuredTool], server_manager: MCPServerManager):
    """创建Chat节点（使用动态工具列表）"""
    
    def chat_node(state: AgentState):
        """Chat节点：处理对话，决定下一步行动"""
        messages = state["messages"]
        
        # 动态生成系统提示（基于当前可用的工具）
        tools_description = _generate_tools_description(tools_list, server_manager)
        system_message = SystemMessage(content=tools_description)
        
        agent_messages = [system_message] + list(messages)
        
        # 绑定工具（使用传入的工具列表）
        llm_with_tools = llm.bind_tools(tools_list)
        
        # 调用LLM
        response = llm_with_tools.invoke(agent_messages)
        
        return {"messages": [response]}
    
    return chat_node


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
        # 工具执行完成，返回chat节点处理结果
        tool_message_count = sum(1 for msg in messages if isinstance(msg, ToolMessage))
        if tool_message_count >= 10:  # 最多执行10次工具调用
            return END
        return "chat"
    
    return END


# ========== 构建图 ==========

def create_agent_graph(config_path: str = "mcp_servers.json"):
    """创建Agent状态图（使用动态工具加载）"""
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
    
    # 动态加载工具
    logger.info("🔍 发现并加载MCP工具...")
    dynamic_tools = load_dynamic_tools(server_manager, force_refresh=False)
    
    if not dynamic_tools:
        logger.warning("⚠️  没有发现任何工具，请检查MCP服务器是否运行")
    
    # 创建节点（使用相同的工具列表）
    chat_node = create_chat_node(llm, dynamic_tools, server_manager)
    tool_node = ToolNode(dynamic_tools)
    
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
    
    # 初始消息
    initial_state: AgentState = {
        "messages": [HumanMessage(content="你是一个AI助手，可以通过MCP服务器读写文件、获取系统时间和操作MySQL数据库。")],
    }
    
    print("🤖 助手: 你好！我可以帮你完成多种任务。")
    
    # 动态显示可用工具示例
    if available_servers > 0:
        print("   可用功能示例：")
        for server_id, server in server_manager.servers.items():
            if server.enabled and server_manager.check_server_health(server_id):
                if server.category == "file_operations":
                    print(f"   [{server.name}]")
                    print("      - '读取文件 test.txt'")
                    print("      - '写入文件 output.txt，内容：Hello World'")
                    print("      - '列出当前目录的文件'")
                elif server.category == "system":
                    print(f"   [{server.name}]")
                    print("      - '现在几点了？'")
                    print("      - '获取当前系统时间'")
                elif server.category == "database":
                    print(f"   [{server.name}]")
                    print("      - '查询数据库 users 表的前10条记录'")
                    print("      - '向数据库插入一条新记录'")
                    print("      - '测试数据库连接'")
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

