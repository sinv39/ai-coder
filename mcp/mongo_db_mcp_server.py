"""
MongoDB MCP服务器
提供从MongoDB查询工具信息的功能
"""

import os
import json
import logging
from typing import Dict, Any, Optional
from flask import Flask, request, jsonify

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# 忽略 isAlive() 弃用警告（来自依赖库，如 Flask）
import warnings
warnings.filterwarnings("ignore", message=".*isAlive.*", category=DeprecationWarning)

app = Flask(__name__)

# MongoDB连接配置（从环境变量读取）
MONGO_HOST = os.getenv("MONGO_HOST", "localhost")
MONGO_PORT = int(os.getenv("MONGO_PORT", "27017"))
MONGO_DATABASE = os.getenv("MONGO_DATABASE", "mcp_tools")
MONGO_USERNAME = os.getenv("MONGO_USERNAME", None)
MONGO_PASSWORD = os.getenv("MONGO_PASSWORD", None)

# 初始化MongoDB客户端
try:
    from mongodb_client import MongoDBClient
    mongo_client = MongoDBClient(
        host=MONGO_HOST,
        port=MONGO_PORT,
        database=MONGO_DATABASE,
        username=MONGO_USERNAME,
        password=MONGO_PASSWORD
    )
    logger.info(f"✅ MongoDB客户端初始化成功: {MONGO_HOST}:{MONGO_PORT}/{MONGO_DATABASE}")
except Exception as e:
    logger.error(f"❌ MongoDB客户端初始化失败: {str(e)}")
    mongo_client = None


def get_service_by_id(tool_id: str) -> Dict[str, Any]:
    """
    根据工具ID查询服务信息
    
    Args:
        tool_id: 工具ID（格式：server_id:tool_name）
    
    Returns:
        包含工具信息的字典
    """
    if not mongo_client:
        raise Exception("MongoDB客户端未初始化，请检查MongoDB连接配置")
    
    try:
        tool_info = mongo_client.get_tool(tool_id)
        
        if not tool_info:
            raise ValueError(f"未找到工具: {tool_id}")
        
        logger.info(f"✅ 成功查询工具: {tool_id}")
        
        return {
            "tool_id": tool_info.get("tool_id", ""),
            "tool_name": tool_info.get("tool_name", ""),
            "tool_description": tool_info.get("tool_description", ""),
            "tool_parameters": tool_info.get("tool_parameters", {}),
            "server_id": tool_info.get("server_id", ""),
            "server_url": tool_info.get("server_url", ""),
            "category": tool_info.get("category"),
            "tags": tool_info.get("tags", []),
            "tool_version": tool_info.get("tool_version", ""),
            "indexed_at": tool_info.get("indexed_at")
        }
    
    except Exception as e:
        logger.error(f"❌ 查询工具失败: {tool_id}, 错误: {str(e)}")
        raise


@app.route('/', methods=['POST'])
def handle_request():
    """处理JSON-RPC请求"""
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({
                "jsonrpc": "2.0",
                "error": {
                    "code": -32700,
                    "message": "Parse error"
                },
                "id": None
            }), 400
        
        method = data.get("method")
        params = data.get("params", {})
        request_id = data.get("id")
        
        # 处理initialize请求
        if method == "initialize":
            return jsonify({
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {
                        "tools": {}
                    },
                    "serverInfo": {
                        "name": "mongo_db_mcp_server",
                        "version": "1.0.0"
                    }
                }
            })
        
        # 处理notifications/initialized通知
        elif method == "notifications/initialized":
            logger.info("✅ 客户端已初始化")
            return jsonify({
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {}
            }), 202
        
        # 处理tools/list请求
        elif method == "tools/list":
            tools = [
                {
                    "name": "get_service_by_id",
                    "description": "根据工具ID查询服务信息。工具ID格式为 server_id:tool_name，例如：file_server:read_file",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "tool_id": {
                                "type": "string",
                                "description": "工具ID，格式：server_id:tool_name"
                            }
                        },
                        "required": ["tool_id"]
                    }
                }
            ]
            
            return jsonify({
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "tools": tools
                }
            })
        
        # 处理tools/call请求
        elif method == "tools/call":
            tool_name = params.get("name")
            arguments = params.get("arguments", {})
            
            if tool_name == "get_service_by_id":
                tool_id = arguments.get("tool_id")
                if not tool_id:
                    return jsonify({
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "error": {
                            "code": -32602,
                            "message": "Invalid params: tool_id is required"
                        }
                    }), 400
                
                try:
                    result = get_service_by_id(tool_id)
                    return jsonify({
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "result": {
                            "content": [
                                {
                                    "type": "text",
                                    "text": json.dumps(result, ensure_ascii=False, indent=2)
                                }
                            ]
                        }
                    })
                except ValueError as e:
                    return jsonify({
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "error": {
                            "code": -32602,
                            "message": str(e)
                        }
                    }), 400
                except Exception as e:
                    return jsonify({
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "error": {
                            "code": -32603,
                            "message": f"Internal error: {str(e)}"
                        }
                    }), 500
            else:
                return jsonify({
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {
                        "code": -32601,
                        "message": f"Method not found: {tool_name}"
                    }
                }), 404
        
        else:
            return jsonify({
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {
                    "code": -32601,
                    "message": f"Method not found: {method}"
                }
            }), 404
    
    except Exception as e:
        logger.error(f"❌ 处理请求失败: {str(e)}")
        return jsonify({
            "jsonrpc": "2.0",
            "id": request.get_json().get("id") if request.get_json() else None,
            "error": {
                "code": -32603,
                "message": f"Internal error: {str(e)}"
            }
        }), 500


@app.route('/health', methods=['GET'])
def health_check():
    """健康检查端点"""
    if mongo_client:
        try:
            # 测试MongoDB连接
            mongo_client.client.admin.command('ping')
            return jsonify({
                "status": "healthy",
                "mongo": "connected"
            }), 200
        except Exception as e:
            return jsonify({
                "status": "unhealthy",
                "mongo": f"disconnected: {str(e)}"
            }), 503
    else:
        return jsonify({
            "status": "unhealthy",
            "mongo": "not initialized"
        }), 503


if __name__ == '__main__':
    port = int(os.getenv("PORT", "3003"))
    logger.info(f"🚀 MongoDB MCP服务器启动在端口 {port}")
    app.run(host='0.0.0.0', port=port, debug=False)

