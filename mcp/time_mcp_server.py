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


def _format_error_response(request_id: Any, error_code: int, message: str, data: str = None) -> Dict[str, Any]:
    """
    格式化错误响应
    
    Args:
        request_id: 请求ID
        error_code: 错误码
        message: 错误消息
        data: 错误详情（可选）
    
    Returns:
        JSON-RPC错误响应
    """
    error_response = {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {
            "code": error_code,
            "message": message
        }
    }
    if data:
        error_response["error"]["data"] = data
    return error_response


def handle_jsonrpc_request(data: Dict[str, Any]) -> Dict[str, Any]:
    """处理JSON-RPC 2.0请求"""
    # 验证JSON-RPC版本
    if data.get("jsonrpc") != "2.0":
        return _format_error_response(
            data.get("id"),
            -32600,
            "Invalid Request",
            "jsonrpc version must be 2.0"
        )
    
    method = data.get("method")
    request_id = data.get("id")
    params = data.get("params", {})
    
    try:
        if method == "initialize":
            # MCP协议：initialize方法
            result = {
                "protocolVersion": "2024-11-05",
                "capabilities": {
                    "tools": {}
                },
                "serverInfo": {
                    "name": "时间MCP服务器",
                    "version": "1.0.0"
                }
            }
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": result
            }
        
        elif method == "notifications/initialized":
            # MCP协议：initialized通知（不需要响应）
            logger.debug("收到 initialized 通知")
            return None
        
        elif method == "tools/list":
            result = handle_tools_list()
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": result
            }
        
        elif method == "tools/call":
            tool_name = params.get("name")
            arguments = params.get("arguments", {})
            
            if not tool_name:
                return _format_error_response(
                    request_id,
                    -32602,
                    "Invalid params",
                    "tools/call 方法需要 name 参数来指定要调用的工具名称"
                )
            
            result = handle_tools_call(tool_name, arguments)
            
            if "error" in result:
                error_msg = result["error"]
                # 根据错误消息判断错误类型
                if "未知的工具" in error_msg or "未实现的工具" in error_msg:
                    return _format_error_response(
                        request_id,
                        -32601,
                        "工具不存在",
                        f"{error_msg}。请使用 tools/list 方法查看可用工具列表。"
                    )
                else:
                    return _format_error_response(
                        request_id,
                        -32602,
                        "工具调用失败",
                        error_msg
                    )
            
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": result
            }
        
        else:
            return _format_error_response(
                request_id,
                -32601,
                "Method not found",
                f"未知的方法: {method}。支持的方法: initialize, notifications/initialized, tools/list, tools/call"
            )
    
    except ValueError as e:
        error_msg = str(e)
        logger.error(f"❌ 参数错误: {error_msg}")
        return _format_error_response(
            request_id,
            -32602,
            "参数错误",
            f"{error_msg}。请检查工具调用参数是否正确。"
        )
    
    except Exception as e:
        logger.error(f"❌ 处理请求失败: {str(e)}", exc_info=True)
        return _format_error_response(
            request_id,
            -32603,
            "Internal error",
            f"服务器内部错误: {str(e)}。如问题持续，请联系管理员。"
        )


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
        
        if response:
            logger.info(f"📤 返回响应: {response.get('result', {}).get('tools', [{}])[0].get('name', '') if 'tools' in response.get('result', {}) else '工具调用'}")
            return jsonify(response)
        else:
            # 通知类请求（如notifications/initialized）不需要响应体
            return jsonify({"jsonrpc": "2.0"}), 200
    
    except Exception as e:
        logger.error(f"❌ 处理请求时出错: {str(e)}", exc_info=True)
        error_response = _format_error_response(
            request.get_json().get("id") if request.is_json else None,
            -32603,
            "Internal error",
            f"服务器处理请求时发生异常: {str(e)}"
        )
        return jsonify(error_response), 500


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

