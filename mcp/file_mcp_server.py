"""
简单的MCP服务器实现
提供本地文件读写功能，使用JSON-RPC 2.0协议
"""

import os
import json
import logging
from pathlib import Path
from typing import Dict, Any, Optional, List
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

# 配置：允许访问的根目录（可选，默认允许所有目录）
ALLOWED_BASE_DIR = os.getenv("MCP_ALLOWED_BASE_DIR", None)


def validate_path(file_path: str) -> Path:
    """
    验证并规范化文件路径，防止路径遍历攻击
    
    Args:
        file_path: 文件或目录路径
        
    Returns:
        规范化后的Path对象
        
    Raises:
        ValueError: 如果路径无效或超出允许范围
    """
    # 规范化路径
    path = Path(file_path).resolve()
    
    # 如果有配置允许的根目录，检查路径是否在允许范围内
    if ALLOWED_BASE_DIR:
        base_dir = Path(ALLOWED_BASE_DIR).resolve()
        try:
            path.relative_to(base_dir)
        except ValueError:
            raise ValueError(f"路径超出允许范围: {file_path}")
    
    return path


def read_file(path: str) -> Dict[str, Any]:
    """
    读取文件内容
    
    Args:
        path: 文件路径
        
    Returns:
        包含文件内容的字典
    """
    try:
        file_path = validate_path(path)
        
        if not file_path.exists():
            raise FileNotFoundError(f"文件不存在: {path}")
        
        if not file_path.is_file():
            raise ValueError(f"路径不是文件: {path}")
        
        # 读取文件内容
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        logger.info(f"✅ 成功读取文件: {path} (大小: {len(content)} 字符)")
        
        return {
            "content": content,
            "path": str(file_path),
            "size": len(content)
        }
    
    except Exception as e:
        logger.error(f"❌ 读取文件失败: {path}, 错误: {str(e)}")
        raise


def write_file(path: str, content: str) -> Dict[str, Any]:
    """
    写入文件内容
    
    Args:
        path: 文件路径
        content: 要写入的内容
        
    Returns:
        包含成功信息的字典
    """
    try:
        file_path = validate_path(path)
        
        # 确保目录存在
        file_path.parent.mkdir(parents=True, exist_ok=True)
        
        # 写入文件
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)
        
        logger.info(f"✅ 成功写入文件: {path} (大小: {len(content)} 字符)")
        
        return {
            "success": True,
            "path": str(file_path),
            "size": len(content),
            "message": f"文件已成功写入: {path}"
        }
    
    except Exception as e:
        logger.error(f"❌ 写入文件失败: {path}, 错误: {str(e)}")
        raise


def list_files(path: Optional[str] = None) -> Dict[str, Any]:
    """
    列出目录中的文件
    
    Args:
        path: 目录路径，如果为None则列出当前工作目录
        
    Returns:
        包含文件列表的字典
    """
    try:
        if path is None:
            dir_path = Path.cwd()
        else:
            dir_path = validate_path(path)
        
        if not dir_path.exists():
            raise FileNotFoundError(f"目录不存在: {path}")
        
        if not dir_path.is_dir():
            raise ValueError(f"路径不是目录: {path}")
        
        # 列出文件和目录
        files = []
        directories = []
        
        for item in dir_path.iterdir():
            item_info = {
                "name": item.name,
                "path": str(item),
                "is_file": item.is_file(),
                "is_dir": item.is_dir(),
                "size": item.stat().st_size if item.is_file() else None
            }
            
            if item.is_file():
                files.append(item_info)
            else:
                directories.append(item_info)
        
        logger.info(f"✅ 成功列出目录: {path or '当前目录'} (文件: {len(files)}, 目录: {len(directories)})")
        
        return {
            "path": str(dir_path),
            "files": files,
            "directories": directories,
            "total_files": len(files),
            "total_directories": len(directories)
        }
    
    except Exception as e:
        logger.error(f"❌ 列出目录失败: {path}, 错误: {str(e)}")
        raise


# 工具注册表
TOOLS = {
    "read_file": {
        "name": "read_file",
        "description": "读取文件内容",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "要读取的文件路径"
                }
            },
            "required": ["path"]
        }
    },
    "write_file": {
        "name": "write_file",
        "description": "写入文件内容",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "要写入的文件路径"
                },
                "content": {
                    "type": "string",
                    "description": "要写入的文件内容"
                }
            },
            "required": ["path", "content"]
        }
    },
    "list_files": {
        "name": "list_files",
        "description": "列出目录中的文件和子目录",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "目录路径（可选，默认为当前工作目录）"
                }
            },
            "required": []
        }
    }
}


def handle_tools_list() -> Dict[str, Any]:
    """
    处理 tools/list 请求，返回可用工具列表
    """
    tools_list = list(TOOLS.values())
    logger.info(f"📋 返回工具列表: {len(tools_list)} 个工具")
    return {
        "tools": tools_list
    }


def handle_tools_call(tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    """
    处理 tools/call 请求，调用指定的工具
    
    Args:
        tool_name: 工具名称
        arguments: 工具参数
        
    Returns:
        工具执行结果
    """
    logger.info(f"🔧 调用工具: {tool_name}, 参数: {arguments}")
    
    if tool_name not in TOOLS:
        raise ValueError(f"未知的工具: {tool_name}")
    
    # 根据工具名称调用相应的函数
    if tool_name == "read_file":
        path = arguments.get("path")
        if not path:
            raise ValueError("read_file 需要 path 参数")
        return read_file(path)
    
    elif tool_name == "write_file":
        path = arguments.get("path")
        content = arguments.get("content", "")
        if not path:
            raise ValueError("write_file 需要 path 参数")
        return write_file(path, content)
    
    elif tool_name == "list_files":
        path = arguments.get("path")
        return list_files(path)
    
    else:
        raise ValueError(f"未实现的工具: {tool_name}")


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
    """
    处理JSON-RPC 2.0请求
    
    Args:
        data: JSON-RPC请求数据
        
    Returns:
        JSON-RPC响应数据
    """
    # 验证JSON-RPC版本
    if data.get("jsonrpc") != "2.0":
        return _format_error_response(
            data.get("id"),
            -32600,
            "Invalid Request",
            "jsonrpc version must be 2.0"
        )
    
    request_id = data.get("id")
    method = data.get("method")
    params = data.get("params", {})
    
    try:
        # 处理不同的方法
        if method == "initialize":
            # MCP协议：initialize方法
            result = {
                "protocolVersion": "2024-11-05",
                "capabilities": {
                    "tools": {}
                },
                "serverInfo": {
                    "name": "文件操作MCP服务器",
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
            tool_arguments = params.get("arguments", {})
            
            if not tool_name:
                return _format_error_response(
                    request_id,
                    -32602,
                    "Invalid params",
                    "tools/call 方法需要 name 参数来指定要调用的工具名称"
                )
            
            result = handle_tools_call(tool_name, tool_arguments)
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
    
    except FileNotFoundError as e:
        logger.error(f"❌ 文件不存在: {str(e)}")
        return _format_error_response(
            request_id,
            -32602,
            "文件不存在",
            f"指定的文件或目录不存在: {str(e)}。请检查文件路径是否正确。"
        )
    
    except ValueError as e:
        error_msg = str(e)
        logger.error(f"❌ 参数错误: {error_msg}")
        # 根据错误消息判断是参数缺失还是其他值错误
        if "需要" in error_msg or "缺少" in error_msg or "参数" in error_msg:
            return _format_error_response(
                request_id,
                -32602,
                "参数错误",
                f"{error_msg}。请检查工具调用参数是否完整。"
            )
        elif "未知的工具" in error_msg or "未实现的工具" in error_msg:
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
                "参数错误",
                error_msg
            )
    
    except PermissionError as e:
        logger.error(f"❌ 权限错误: {str(e)}")
        return _format_error_response(
            request_id,
            -32001,
            "权限不足",
            f"无权执行此操作: {str(e)}。请检查文件权限或配置的允许访问目录。"
        )
    
    except OSError as e:
        logger.error(f"❌ 系统错误: {str(e)}")
        return _format_error_response(
            request_id,
            -32002,
            "系统错误",
            f"文件系统操作失败: {str(e)}。请检查磁盘空间和文件系统状态。"
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
    """
    处理所有POST请求（JSON-RPC 2.0）
    """
    try:
        # 解析JSON请求
        data = request.get_json()
        
        if not data:
            return jsonify({
                "jsonrpc": "2.0",
                "id": None,
                "error": {
                    "code": -32700,
                    "message": "Parse error",
                    "data": "Invalid JSON"
                }
            }), 400
        
        logger.info(f"📥 收到请求: method={data.get('method')}, id={data.get('id')}")
        
        # 处理请求
        response = handle_jsonrpc_request(data)
        
        logger.info(f"📤 返回响应: id={response.get('id')}, 成功={('error' not in response)}")
        
        return jsonify(response)
    
    except Exception as e:
        logger.error(f"❌ 处理请求时发生异常: {str(e)}", exc_info=True)
        error_response = _format_error_response(
            None,
            -32603,
            "Internal error",
            f"服务器处理请求时发生异常: {str(e)}"
        )
        return jsonify(error_response), 500


@app.route('/health', methods=['GET'])
def health_check():
    """
    健康检查端点
    """
    return jsonify({
        "status": "healthy",
        "service": "MCP Server",
        "tools": len(TOOLS)
    })


def main():
    """启动服务器"""
    # 从环境变量读取端口，默认3000
    # 明确指定端口，防止Flask使用默认的5000端口
    port = int(os.getenv("MCP_SERVER_PORT", "3000"))
    host = os.getenv("MCP_SERVER_HOST", "0.0.0.0")
    
    # 如果环境变量FLASK_RUN_PORT存在，可能会覆盖我们的设置
    # 所以明确清除它，确保使用我们指定的端口
    if "FLASK_RUN_PORT" in os.environ:
        logger.warning(f"⚠️  检测到FLASK_RUN_PORT环境变量，将被忽略，使用MCP_SERVER_PORT={port}")
    
    logger.info("=" * 60)
    logger.info("🚀 启动MCP服务器")
    logger.info("=" * 60)
    logger.info(f"📍 地址: http://{host}:{port}")
    logger.info(f"📋 可用工具: {len(TOOLS)} 个")
    for tool_name in TOOLS.keys():
        logger.info(f"   - {tool_name}")
    
    if ALLOWED_BASE_DIR:
        logger.info(f"🔒 限制访问目录: {ALLOWED_BASE_DIR}")
    else:
        logger.info("⚠️  未限制访问目录（允许访问所有路径）")
    
    logger.info("=" * 60)
    
    # 确保端口明确设置为3000（如果环境变量未设置）
    # 防止Flask使用默认的5000端口
    if port != 3000:
        logger.info(f"ℹ️  使用自定义端口: {port} (从环境变量MCP_SERVER_PORT读取)")
    else:
        logger.info(f"ℹ️  使用默认端口: {port}")
    
    logger.info(f"🚀 正在启动服务器...")
    
    # 明确指定端口，确保不会使用Flask默认的5000端口
    app.run(host=host, port=port, debug=False)


if __name__ == "__main__":
    # 直接运行Python文件时，调用main()函数
    main()
else:
    # 当使用 Flask CLI (python -m flask run) 时，需要设置环境变量
    # 或者在这里配置默认端口
    import sys
    if 'flask' in sys.modules:
        # Flask CLI 模式下，设置默认端口
        if not os.getenv("FLASK_RUN_PORT"):
            os.environ["FLASK_RUN_PORT"] = "3000"
        if not os.getenv("FLASK_RUN_HOST"):
            os.environ["FLASK_RUN_HOST"] = "0.0.0.0"

