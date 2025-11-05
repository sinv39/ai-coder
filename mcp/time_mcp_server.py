"""
时间MCP服务器
提供系统时间读取功能
"""

import os
import json
import logging
from datetime import datetime
from typing import Dict, Any
from flask import Flask, request, jsonify

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


def get_current_time() -> Dict[str, Any]:
    """获取当前系统时间"""
    now = datetime.now()
    return {
        "timestamp": now.timestamp(),
        "datetime": now.isoformat(),
        "date": now.strftime("%Y-%m-%d"),
        "time": now.strftime("%H:%M:%S"),
        "timezone": str(now.astimezone().tzinfo),
        "formatted": now.strftime("%Y-%m-%d %H:%M:%S"),
        "weekday": now.strftime("%A"),
        "year": now.year,
        "month": now.month,
        "day": now.day,
        "hour": now.hour,
        "minute": now.minute,
        "second": now.second
    }


def get_time_info(format_type: str = "full") -> Dict[str, Any]:
    """
    获取时间信息
    
    参数:
    - format_type: 返回格式类型
      * "full" - 完整信息（默认）
      * "simple" - 简单格式（仅日期时间字符串）
      * "timestamp" - 仅时间戳
    """
    time_data = get_current_time()
    
    if format_type == "simple":
        return {
            "datetime": time_data["formatted"],
            "date": time_data["date"],
            "time": time_data["time"]
        }
    elif format_type == "timestamp":
        return {
            "timestamp": time_data["timestamp"]
        }
    else:  # full
        return time_data


# 定义工具
TOOLS = {
    "get_current_time": {
        "name": "get_current_time",
        "description": "获取当前系统时间，返回完整的时间信息（时间戳、日期时间、时区等）",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    "get_time_info": {
        "name": "get_time_info",
        "description": "获取时间信息，支持多种格式（full/simple/timestamp）",
        "inputSchema": {
            "type": "object",
            "properties": {
                "format_type": {
                    "type": "string",
                    "enum": ["full", "simple", "timestamp"],
                    "description": "返回格式类型：full（完整信息）、simple（简单格式）、timestamp（仅时间戳）",
                    "default": "full"
                }
            },
            "required": []
        }
    }
}


def handle_tools_list() -> Dict[str, Any]:
    """处理 tools/list 请求"""
    return {
        "tools": list(TOOLS.values())
    }


def handle_tools_call(tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    """处理 tools/call 请求"""
    if tool_name == "get_current_time":
        result = get_current_time()
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(result, ensure_ascii=False, indent=2)
                }
            ]
        }
    
    elif tool_name == "get_time_info":
        format_type = arguments.get("format_type", "full")
        result = get_time_info(format_type)
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(result, ensure_ascii=False, indent=2)
                }
            ]
        }
    
    else:
        return {
            "error": f"未知工具: {tool_name}",
            "available_tools": list(TOOLS.keys())
        }


def handle_jsonrpc_request(data: Dict[str, Any]) -> Dict[str, Any]:
    """处理JSON-RPC 2.0请求"""
    method = data.get("method")
    request_id = data.get("id")
    
    if method == "tools/list":
        result = handle_tools_list()
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": result
        }
    
    elif method == "tools/call":
        params = data.get("params", {})
        tool_name = params.get("name")
        arguments = params.get("arguments", {})
        
        if not tool_name:
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {
                    "code": -32602,
                    "message": "参数错误",
                    "data": "缺少工具名称"
                }
            }
        
        result = handle_tools_call(tool_name, arguments)
        
        if "error" in result:
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {
                    "code": -32601,
                    "message": result["error"]
                }
            }
        
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": result
        }
    
    else:
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {
                "code": -32601,
                "message": f"未知方法: {method}"
            }
        }


@app.route('/', methods=['POST'])
def handle_request():
    """处理JSON-RPC请求"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({
                "jsonrpc": "2.0",
                "id": None,
                "error": {
                    "code": -32700,
                    "message": "解析错误"
                }
            }), 400
        
        logger.info(f"📥 收到请求: {data.get('method')} (ID: {data.get('id')})")
        
        response = handle_jsonrpc_request(data)
        
        logger.info(f"📤 返回响应: {response.get('result', {}).get('tools', [{}])[0].get('name', '') if 'tools' in response.get('result', {}) else '工具调用'}")
        
        return jsonify(response)
    
    except Exception as e:
        logger.error(f"❌ 处理请求时出错: {str(e)}")
        return jsonify({
            "jsonrpc": "2.0",
            "id": request.get_json().get("id") if request.is_json else None,
            "error": {
                "code": -32603,
                "message": f"内部错误: {str(e)}"
            }
        }), 500


@app.route('/health', methods=['GET'])
def health_check():
    """健康检查端点"""
    return jsonify({
        "status": "healthy",
        "service": "time_mcp_server",
        "timestamp": datetime.now().isoformat()
    })


def main():
    """启动服务器"""
    port = int(os.getenv("TIME_MCP_SERVER_PORT", "3001"))
    host = os.getenv("TIME_MCP_SERVER_HOST", "0.0.0.0")
    
    logger.info(f"🚀 启动时间MCP服务器...")
    logger.info(f"📍 地址: http://{host}:{port}")
    logger.info(f"💡 健康检查: http://{host}:{port}/health")
    logger.info(f"📋 可用工具: {', '.join(TOOLS.keys())}")
    
    app.run(host=host, port=port, debug=False)


if __name__ == "__main__":
    main()

