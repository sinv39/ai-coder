"""
测试动态工具加载功能
用于验证MCP服务器管理器、动态工具加载器是否正常工作
"""

import os
import sys
import logging
from mcp_server_manager import MCPServerManager
from dynamic_tool_loader import load_dynamic_tools

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def test_server_manager():
    """测试服务器管理器"""
    print("=" * 60)
    print("📋 测试1: MCP服务器管理器")
    print("=" * 60)
    
    # 初始化管理器
    config_path = "mcp_servers.json"
    if not os.path.exists(config_path):
        print(f"❌ 配置文件不存在: {config_path}")
        return False
    
    manager = MCPServerManager(config_path)
    
    # 显示加载的服务器
    print(f"\n✅ 加载了 {len(manager.servers)} 个服务器配置:")
    for server_id, server in manager.servers.items():
        print(f"   - {server.name} ({server_id})")
        print(f"     URL: {server.url}")
        print(f"     状态: {'启用' if server.enabled else '禁用'}")
        print(f"     类别: {server.category}")
        print()
    
    return True


def test_server_health():
    """测试服务器健康检查"""
    print("=" * 60)
    print("🏥 测试2: 服务器健康检查")
    print("=" * 60)
    
    manager = MCPServerManager("mcp_servers.json")
    
    healthy_servers = []
    for server_id, server in manager.servers.items():
        if not server.enabled:
            print(f"⏸️  {server.name} ({server_id}) - 已禁用")
            continue
        
        is_healthy = manager.check_server_health(server_id)
        if is_healthy:
            print(f"✅ {server.name} ({server_id}) - 健康")
            healthy_servers.append(server_id)
        else:
            print(f"❌ {server.name} ({server_id}) - 无法连接")
            print(f"   请确保服务器正在运行: {server.url}")
    
    print(f"\n📊 统计: {len(healthy_servers)}/{len(manager.servers)} 个服务器可用")
    return healthy_servers


def test_tool_discovery():
    """测试工具发现"""
    print("=" * 60)
    print("🔍 测试3: 工具发现")
    print("=" * 60)
    
    manager = MCPServerManager("mcp_servers.json")
    
    # 发现所有工具
    discovered = manager.discover_tools(force_refresh=True)
    
    total_tools = 0
    for server_id, tools in discovered.items():
        server = manager.servers.get(server_id)
        server_name = server.name if server else server_id
        print(f"\n📦 {server_name} ({server_id}):")
        print(f"   发现 {len(tools)} 个工具:")
        
        for tool_info in tools:
            print(f"   - {tool_info.name}")
            print(f"     描述: {tool_info.description}")
            
            # 显示参数
            params = tool_info.parameters.get("properties", {})
            required = tool_info.parameters.get("required", [])
            if params:
                print(f"     参数:")
                for param_name, param_info in params.items():
                    param_type = param_info.get("type", "unknown")
                    is_required = param_name in required
                    print(f"       - {param_name} ({param_type}) {'[必需]' if is_required else '[可选]'}")
            
            total_tools += 1
            print()
    
    print(f"📊 总计: 发现 {total_tools} 个工具")
    return discovered


def test_dynamic_tool_loading():
    """测试动态工具加载"""
    print("=" * 60)
    print("⚙️  测试4: 动态工具加载（创建LangChain工具）")
    print("=" * 60)
    
    manager = MCPServerManager("mcp_servers.json")
    
    # 加载动态工具
    langchain_tools = load_dynamic_tools(manager, force_refresh=False)
    
    print(f"\n✅ 成功加载 {len(langchain_tools)} 个LangChain工具:\n")
    
    for tool in langchain_tools:
        print(f"🔧 {tool.name}")
        print(f"   描述: {tool.description}")
        
        # 显示参数schema
        if hasattr(tool, 'args_schema') and tool.args_schema:
            schema_fields = tool.args_schema.schema().get("properties", {})
            if schema_fields:
                print(f"   参数:")
                for field_name, field_info in schema_fields.items():
                    field_type = field_info.get("type", "unknown")
                    field_desc = field_info.get("description", "")
                    print(f"     - {field_name} ({field_type})")
                    if field_desc:
                        print(f"       {field_desc}")
        print()
    
    return langchain_tools


def test_tool_name_format():
    """测试工具名称格式"""
    print("=" * 60)
    print("📝 测试5: 工具名称格式验证")
    print("=" * 60)
    
    manager = MCPServerManager("mcp_servers.json")
    langchain_tools = load_dynamic_tools(manager, force_refresh=False)
    
    print("\n工具名称格式检查 (应为: server_id_tool_name):\n")
    
    all_valid = True
    for tool in langchain_tools:
        parts = tool.name.split('_', 1)
        if len(parts) == 2:
            server_id, tool_name = parts
            if server_id in manager.servers:
                print(f"✅ {tool.name}")
                print(f"   服务器ID: {server_id}")
                print(f"   工具名: {tool_name}")
            else:
                print(f"⚠️  {tool.name} - 服务器ID '{server_id}' 不在配置中")
                all_valid = False
        else:
            print(f"❌ {tool.name} - 格式不正确")
            all_valid = False
        print()
    
    if all_valid:
        print("✅ 所有工具名称格式正确")
    else:
        print("❌ 发现格式问题")
    
    return all_valid


def main():
    """主测试函数"""
    print("\n" + "=" * 60)
    print("🧪 动态工具加载系统测试")
    print("=" * 60 + "\n")
    
    results = {}
    
    # 测试1: 服务器管理器
    try:
        results['server_manager'] = test_server_manager()
    except Exception as e:
        print(f"❌ 测试失败: {e}")
        results['server_manager'] = False
    
    print("\n")
    
    # 测试2: 服务器健康检查
    try:
        healthy_servers = test_server_health()
        results['server_health'] = len(healthy_servers) > 0
    except Exception as e:
        print(f"❌ 测试失败: {e}")
        results['server_health'] = False
    
    print("\n")
    
    # 测试3: 工具发现
    try:
        discovered = test_tool_discovery()
        results['tool_discovery'] = len(discovered) > 0
    except Exception as e:
        print(f"❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        results['tool_discovery'] = False
    
    print("\n")
    
    # 测试4: 动态工具加载
    try:
        langchain_tools = test_dynamic_tool_loading()
        results['dynamic_loading'] = len(langchain_tools) > 0
    except Exception as e:
        print(f"❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        results['dynamic_loading'] = False
    
    print("\n")
    
    # 测试5: 工具名称格式
    try:
        results['name_format'] = test_tool_name_format()
    except Exception as e:
        print(f"❌ 测试失败: {e}")
        results['name_format'] = False
    
    # 总结
    print("\n" + "=" * 60)
    print("📊 测试总结")
    print("=" * 60)
    
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    
    for test_name, result in results.items():
        status = "✅ 通过" if result else "❌ 失败"
        print(f"{test_name}: {status}")
    
    print(f"\n总计: {passed}/{total} 个测试通过")
    
    if passed == total:
        print("\n🎉 所有测试通过！动态工具加载系统工作正常。")
    else:
        print("\n⚠️  部分测试失败，请检查配置和MCP服务器状态。")
    
    return passed == total


if __name__ == "__main__":
    # 确保在正确的目录下运行
    script_dir = os.path.dirname(os.path.abspath(__file__))
    # 如果脚本在mcp目录下，切换到mcp目录并添加父目录到路径
    if os.path.basename(script_dir) == "mcp":
        os.chdir(script_dir)
        parent_dir = os.path.dirname(script_dir)
        if parent_dir not in sys.path:
            sys.path.insert(0, parent_dir)
    
    success = main()
    sys.exit(0 if success else 1)

