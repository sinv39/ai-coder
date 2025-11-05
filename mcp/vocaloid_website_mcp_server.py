"""
Vocaloid音乐网站 MCP 服务器
提供对 Vocaloid 猜歌游戏网站 API 的访问，使用 JSON-RPC 2.0 协议
"""

import os
import json
import logging
from typing import Dict, Any, Optional
from flask import Flask, request, jsonify
import requests
from pathlib import Path

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

# Vocaloid 网站基础 URL
BASE_URL = os.getenv("VOCALOID_WEBSITE_URL", "http://123.60.40.72:10001")


def get_random_music() -> Dict[str, Any]:
    """获取一首随机歌曲"""
    try:
        response = requests.get(f"{BASE_URL}/api/music/random", timeout=10)
        response.raise_for_status()
        result = response.json()
        logger.info(f"✅ 获取随机歌曲: {result.get('title', '未知')}")
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(result, ensure_ascii=False, indent=2)
                }
            ]
        }
    except requests.exceptions.RequestException as e:
        logger.error(f"❌ 获取随机歌曲失败: {str(e)}")
        raise Exception(f"获取随机歌曲失败: {str(e)}")


def get_stats() -> Dict[str, Any]:
    """获取当前会话的统计信息"""
    try:
        response = requests.get(f"{BASE_URL}/api/music/stats", timeout=10)
        response.raise_for_status()
        result = response.json()
        logger.info(f"✅ 获取统计信息: 已播放 {result.get('playedCount', 0)} 首, 剩余 {result.get('remainingCount', 0)} 首")
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(result, ensure_ascii=False, indent=2)
                }
            ]
        }
    except requests.exceptions.RequestException as e:
        logger.error(f"❌ 获取统计信息失败: {str(e)}")
        raise Exception(f"获取统计信息失败: {str(e)}")


def upload_music(file_path: str, title: str) -> Dict[str, Any]:
    """
    上传歌曲
    
    参数:
    - file_path: 音频文件路径（本地文件）
    - title: 歌曲名称
    """
    try:
        # 检查文件是否存在
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"文件不存在: {file_path}")
        
        # 检查文件大小（5MB限制）
        file_size = os.path.getsize(file_path)
        if file_size > 5 * 1024 * 1024:  # 5MB
            raise ValueError(f"文件大小超过5MB限制: {file_size / 1024 / 1024:.2f}MB")
        
        # 准备文件上传
        with open(file_path, 'rb') as f:
            files = {'file': (os.path.basename(file_path), f, 'audio/mpeg')}
            data = {'title': title}
            
            response = requests.post(
                f"{BASE_URL}/api/music/upload",
                files=files,
                data=data,
                timeout=30
            )
        
        response.raise_for_status()
        
        # 响应可能是纯文本或JSON
        if response.headers.get('content-type', '').startswith('application/json'):
            result = response.json()
        else:
            result = {"message": response.text}
        
        logger.info(f"✅ 上传歌曲成功: {title}")
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(result, ensure_ascii=False, indent=2)
                }
            ]
        }
    except requests.exceptions.RequestException as e:
        logger.error(f"❌ 上传歌曲失败: {str(e)}")
        raise Exception(f"上传歌曲失败: {str(e)}")
    except Exception as e:
        logger.error(f"❌ 上传歌曲失败: {str(e)}")
        raise


def list_music() -> Dict[str, Any]:
    """获取所有歌曲列表"""
    try:
        response = requests.get(f"{BASE_URL}/api/music/list", timeout=10)
        response.raise_for_status()
        result = response.json()
        logger.info(f"✅ 获取歌曲列表: {len(result)} 首歌曲")
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(result, ensure_ascii=False, indent=2)
                }
            ]
        }
    except requests.exceptions.RequestException as e:
        logger.error(f"❌ 获取歌曲列表失败: {str(e)}")
        raise Exception(f"获取歌曲列表失败: {str(e)}")


def play_music(music_id: int) -> Dict[str, Any]:
    """
    获取歌曲播放信息（返回播放URL）
    
    参数:
    - music_id: 歌曲ID
    """
    try:
        # 由于播放接口返回音频流，我们返回播放URL
        play_url = f"{BASE_URL}/api/music/play/{music_id}"
        
        # 验证歌曲是否存在（通过检查响应状态）
        response = requests.head(play_url, timeout=10, allow_redirects=True)
        if response.status_code == 404:
            raise ValueError(f"歌曲不存在: ID {music_id}")
        
        logger.info(f"✅ 获取歌曲播放信息: ID {music_id}")
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps({
                        "id": music_id,
                        "play_url": play_url,
                        "message": "使用此URL可以播放音频文件"
                    }, ensure_ascii=False, indent=2)
                }
            ]
        }
    except requests.exceptions.RequestException as e:
        logger.error(f"❌ 获取歌曲播放信息失败: {str(e)}")
        raise Exception(f"获取歌曲播放信息失败: {str(e)}")


def delete_music(music_id: int) -> Dict[str, Any]:
    """
    删除歌曲
    
    参数:
    - music_id: 歌曲ID
    """
    try:
        response = requests.delete(f"{BASE_URL}/api/music/{music_id}", timeout=10)
        response.raise_for_status()
        
        # 响应可能是纯文本或JSON
        if response.headers.get('content-type', '').startswith('application/json'):
            result = response.json()
        else:
            result = {"message": response.text}
        
        logger.info(f"✅ 删除歌曲成功: ID {music_id}")
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(result, ensure_ascii=False, indent=2)
                }
            ]
        }
    except requests.exceptions.RequestException as e:
        logger.error(f"❌ 删除歌曲失败: {str(e)}")
        raise Exception(f"删除歌曲失败: {str(e)}")


def reset_session() -> Dict[str, Any]:
    """重置当前会话，清空已播放记录"""
    try:
        response = requests.post(f"{BASE_URL}/api/music/reset", timeout=10)
        response.raise_for_status()
        
        # 响应可能是纯文本或JSON
        if response.headers.get('content-type', '').startswith('application/json'):
            result = response.json()
        else:
            result = {"message": response.text}
        
        logger.info("✅ 重置会话成功")
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(result, ensure_ascii=False, indent=2)
                }
            ]
        }
    except requests.exceptions.RequestException as e:
        logger.error(f"❌ 重置会话失败: {str(e)}")
        raise Exception(f"重置会话失败: {str(e)}")


# 定义工具
TOOLS = {
    "get_random_music": {
        "name": "get_random_music",
        "description": "获取一首随机歌曲（智能随机，避免重复）",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    "get_stats": {
        "name": "get_stats",
        "description": "获取当前会话的统计信息（已播放数量、剩余数量）",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    "upload_music": {
        "name": "upload_music",
        "description": "上传音频文件到服务器（支持MP3等格式，最大5MB）",
        "parameters": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "音频文件的本地路径"
                },
                "title": {
                    "type": "string",
                    "description": "歌曲名称（最大255字符）"
                }
            },
            "required": ["file_path", "title"]
        }
    },
    "list_music": {
        "name": "list_music",
        "description": "获取所有歌曲列表，按上传时间倒序排列",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    "play_music": {
        "name": "play_music",
        "description": "获取歌曲的播放URL（用于播放音频文件）",
        "parameters": {
            "type": "object",
            "properties": {
                "music_id": {
                    "type": "integer",
                    "description": "歌曲ID"
                }
            },
            "required": ["music_id"]
        }
    },
    "delete_music": {
        "name": "delete_music",
        "description": "删除指定ID的歌曲",
        "parameters": {
            "type": "object",
            "properties": {
                "music_id": {
                    "type": "integer",
                    "description": "要删除的歌曲ID"
                }
            },
            "required": ["music_id"]
        }
    },
    "reset_session": {
        "name": "reset_session",
        "description": "重置当前会话，清空已播放记录",
        "parameters": {
            "type": "object",
            "properties": {},
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
    if tool_name == "get_random_music":
        return get_random_music()
    
    elif tool_name == "get_stats":
        return get_stats()
    
    elif tool_name == "upload_music":
        file_path = arguments.get("file_path")
        title = arguments.get("title")
        if not file_path:
            raise ValueError("upload_music 需要 file_path 参数")
        if not title:
            raise ValueError("upload_music 需要 title 参数")
        return upload_music(file_path, title)
    
    elif tool_name == "list_music":
        return list_music()
    
    elif tool_name == "play_music":
        music_id = arguments.get("music_id")
        if music_id is None:
            raise ValueError("play_music 需要 music_id 参数")
        try:
            music_id = int(music_id)
        except (ValueError, TypeError):
            raise ValueError(f"music_id 必须是整数: {music_id}")
        return play_music(music_id)
    
    elif tool_name == "delete_music":
        music_id = arguments.get("music_id")
        if music_id is None:
            raise ValueError("delete_music 需要 music_id 参数")
        try:
            music_id = int(music_id)
        except (ValueError, TypeError):
            raise ValueError(f"music_id 必须是整数: {music_id}")
        return delete_music(music_id)
    
    elif tool_name == "reset_session":
        return reset_session()
    
    else:
        raise ValueError(f"未实现的工具: {tool_name}")


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
        return {
            "jsonrpc": "2.0",
            "id": data.get("id"),
            "error": {
                "code": -32600,
                "message": "无效的请求"
            }
        }
    
    method = data.get("method")
    params = data.get("params", {})
    request_id = data.get("id")
    
    try:
        if method == "tools/list":
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
                return {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {
                        "code": -32602,
                        "message": "缺少工具名称"
                    }
                }
            
            result = handle_tools_call(tool_name, tool_arguments)
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
    
    except Exception as e:
        logger.error(f"❌ 处理请求时出错: {str(e)}")
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {
                "code": -32603,
                "message": f"内部错误: {str(e)}"
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
        
        logger.info(f"📤 返回响应: {data.get('method')}")
        
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
    try:
        # 尝试访问网站基础URL
        response = requests.get(f"{BASE_URL}/", timeout=5)
        return jsonify({
            "status": "healthy",
            "base_url": BASE_URL,
            "website_accessible": response.status_code == 200
        }), 200
    except Exception as e:
        return jsonify({
            "status": "unhealthy",
            "base_url": BASE_URL,
            "error": str(e)
        }), 503


if __name__ == "__main__":
    port = int(os.getenv("PORT", 3003))
    logger.info(f"🚀 Vocaloid网站 MCP 服务器启动在端口 {port}")
    logger.info(f"📡 网站地址: {BASE_URL}")
    app.run(host="0.0.0.0", port=port, debug=False)

