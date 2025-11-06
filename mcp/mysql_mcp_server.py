"""
MySQL MCP服务器
提供MySQL数据库连接和CRUD操作功能
"""

import os
import json
import logging
import re
from typing import Dict, Any, Optional, List, Tuple
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

# 尝试导入 MySQL 客户端库
try:
    import pymysql
    MYSQL_AVAILABLE = True
    MYSQL_LIB = "pymysql"
except ImportError:
    try:
        import mysql.connector
        MYSQL_AVAILABLE = True
        MYSQL_LIB = "mysql.connector"
    except ImportError:
        MYSQL_AVAILABLE = False
        MYSQL_LIB = None
        logger.warning("⚠️  未安装 MySQL 客户端库，请安装: pip install pymysql 或 pip install mysql-connector-python")


# 禁止执行的 SQL 关键字（DDL 操作）
FORBIDDEN_KEYWORDS = [
    'CREATE', 'ALTER', 'DROP', 'TRUNCATE', 'RENAME',
    'GRANT', 'REVOKE', 'FLUSH', 'LOCK', 'UNLOCK',
    'BACKUP', 'RESTORE', 'LOAD DATA', 'LOAD_FILE'
]

# 允许的 SQL 操作（CRUD）
ALLOWED_KEYWORDS = ['SELECT', 'INSERT', 'UPDATE', 'DELETE']


def validate_sql(sql: str) -> Tuple[bool, str]:
    """
    验证 SQL 语句是否安全（只允许 CRUD 操作）
    
    Args:
        sql: SQL 语句
        
    Returns:
        (是否安全, 错误信息)
    """
    sql_upper = sql.strip().upper()
    
    # 检查是否包含禁止的关键字
    for keyword in FORBIDDEN_KEYWORDS:
        if keyword in sql_upper:
            return False, f"不允许执行 DDL 操作: {keyword}"
    
    # 检查是否包含允许的关键字
    has_allowed = any(keyword in sql_upper for keyword in ALLOWED_KEYWORDS)
    
    if not has_allowed:
        return False, "SQL 语句必须包含 SELECT、INSERT、UPDATE 或 DELETE 操作"
    
    # 检查是否包含多个语句（防止 SQL 注入）
    if ';' in sql and sql.count(';') > 1:
        return False, "不允许执行多个 SQL 语句"
    
    return True, ""


def create_connection(config: Dict[str, Any]):
    """
    创建 MySQL 数据库连接
    
    Args:
        config: 数据库配置字典，包含:
            - host: MySQL 服务器地址
            - port: MySQL 端口（默认3306）
            - user: 用户名
            - password: 密码
            - database: 数据库名
            
    Returns:
        MySQL 连接对象
    """
    host = config.get('host') or config.get('ip')
    port = int(config.get('port', 3306))
    user = config.get('user') or config.get('username')
    password = config.get('password')
    database = config.get('database') or config.get('db')
    
    if not all([host, user, password, database]):
        raise ValueError("缺少必需的数据库连接参数: host, user, password, database")
    
    try:
        if MYSQL_LIB == "pymysql":
            connection = pymysql.connect(
                host=host,
                port=port,
                user=user,
                password=password,
                database=database,
                charset='utf8mb4',
                cursorclass=pymysql.cursors.DictCursor,
                autocommit=False
            )
        elif MYSQL_LIB == "mysql.connector":
            connection = mysql.connector.connect(
                host=host,
                port=port,
                user=user,
                password=password,
                database=database,
                charset='utf8mb4',
                autocommit=False
            )
        else:
            raise ImportError("未安装 MySQL 客户端库")
        
        logger.info(f"✅ 成功连接到 MySQL: {host}:{port}/{database}")
        return connection
    
    except Exception as e:
        logger.error(f"❌ 连接 MySQL 失败: {str(e)}")
        raise


def execute_query(connection_config: Dict[str, Any], sql: str) -> Dict[str, Any]:
    """
    执行 SQL 查询（SELECT）
    
    Args:
        connection_config: 数据库连接配置
        sql: SQL 查询语句
        
    Returns:
        查询结果字典
    """
    # 验证 SQL
    is_safe, error_msg = validate_sql(sql)
    if not is_safe:
        raise ValueError(error_msg)
    
    connection = None
    cursor = None
    
    try:
        connection = create_connection(connection_config)
        cursor = connection.cursor()
        
        logger.info(f"🔍 执行查询: {sql[:100]}...")
        cursor.execute(sql)
        
        # 获取结果
        if MYSQL_LIB == "pymysql":
            rows = cursor.fetchall()
            # pymysql 返回的是字典列表
            results = list(rows) if rows else []
        else:  # mysql.connector
            rows = cursor.fetchall()
            columns = [desc[0] for desc in cursor.description]
            results = [dict(zip(columns, row)) for row in rows] if rows else []
        
        return {
            "success": True,
            "rows": results,
            "row_count": len(results),
            "sql": sql
        }
    
    except Exception as e:
        logger.error(f"❌ 执行查询失败: {str(e)}")
        raise
    
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()


def execute_update(connection_config: Dict[str, Any], sql: str) -> Dict[str, Any]:
    """
    执行 SQL 更新操作（INSERT, UPDATE, DELETE）
    
    Args:
        connection_config: 数据库连接配置
        sql: SQL 更新语句
        
    Returns:
        更新结果字典
    """
    # 验证 SQL
    is_safe, error_msg = validate_sql(sql)
    if not is_safe:
        raise ValueError(error_msg)
    
    connection = None
    cursor = None
    
    try:
        connection = create_connection(connection_config)
        cursor = connection.cursor()
        
        logger.info(f"✏️  执行更新: {sql[:100]}...")
        cursor.execute(sql)
        
        # 获取影响的行数
        affected_rows = cursor.rowcount
        
        # 提交事务
        connection.commit()
        
        # 获取最后插入的 ID（如果是 INSERT）
        last_insert_id = None
        if sql.strip().upper().startswith('INSERT'):
            if MYSQL_LIB == "pymysql":
                last_insert_id = connection.insert_id()
            else:
                cursor.execute("SELECT LAST_INSERT_ID()")
                last_insert_id = cursor.fetchone()[0]
        
        return {
            "success": True,
            "affected_rows": affected_rows,
            "last_insert_id": last_insert_id,
            "sql": sql
        }
    
    except Exception as e:
        if connection:
            connection.rollback()
        logger.error(f"❌ 执行更新失败: {str(e)}")
        raise
    
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()


# 工具注册表
TOOLS = {
    "execute_query": {
        "name": "execute_query",
        "description": "执行 SQL 查询（SELECT），返回查询结果",
        "inputSchema": {
            "type": "object",
            "properties": {
                "connection": {
                    "type": "object",
                    "description": "数据库连接配置",
                    "properties": {
                        "host": {"type": "string", "description": "MySQL 服务器地址（IP）"},
                        "port": {"type": "integer", "description": "MySQL 端口（默认3306）"},
                        "user": {"type": "string", "description": "用户名"},
                        "username": {"type": "string", "description": "用户名（别名）"},
                        "password": {"type": "string", "description": "密码"},
                        "database": {"type": "string", "description": "数据库名"},
                        "db": {"type": "string", "description": "数据库名（别名）"}
                    },
                    "required": ["host", "user", "password", "database"]
                },
                "sql": {
                    "type": "string",
                    "description": "SQL 查询语句（SELECT）"
                }
            },
            "required": ["connection", "sql"]
        }
    },
    "execute_update": {
        "name": "execute_update",
        "description": "执行 SQL 更新操作（INSERT, UPDATE, DELETE），返回影响的行数",
        "inputSchema": {
            "type": "object",
            "properties": {
                "connection": {
                    "type": "object",
                    "description": "数据库连接配置",
                    "properties": {
                        "host": {"type": "string", "description": "MySQL 服务器地址（IP）"},
                        "port": {"type": "integer", "description": "MySQL 端口（默认3306）"},
                        "user": {"type": "string", "description": "用户名"},
                        "username": {"type": "string", "description": "用户名（别名）"},
                        "password": {"type": "string", "description": "密码"},
                        "database": {"type": "string", "description": "数据库名"},
                        "db": {"type": "string", "description": "数据库名（别名）"}
                    },
                    "required": ["host", "user", "password", "database"]
                },
                "sql": {
                    "type": "string",
                    "description": "SQL 更新语句（INSERT, UPDATE, DELETE）"
                }
            },
            "required": ["connection", "sql"]
        }
    },
    "test_connection": {
        "name": "test_connection",
        "description": "测试数据库连接是否正常",
        "inputSchema": {
            "type": "object",
            "properties": {
                "connection": {
                    "type": "object",
                    "description": "数据库连接配置",
                    "properties": {
                        "host": {"type": "string", "description": "MySQL 服务器地址（IP）"},
                        "port": {"type": "integer", "description": "MySQL 端口（默认3306）"},
                        "user": {"type": "string", "description": "用户名"},
                        "username": {"type": "string", "description": "用户名（别名）"},
                        "password": {"type": "string", "description": "密码"},
                        "database": {"type": "string", "description": "数据库名"},
                        "db": {"type": "string", "description": "数据库名（别名）"}
                    },
                    "required": ["host", "user", "password", "database"]
                }
            },
            "required": ["connection"]
        }
    }
}


def handle_tools_list() -> Dict[str, Any]:
    """处理 tools/list 请求"""
    if not MYSQL_AVAILABLE:
        logger.warning("⚠️  MySQL 客户端库未安装，部分功能不可用")
    
    return {
        "tools": list(TOOLS.values())
    }


def handle_tools_call(tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    """处理 tools/call 请求"""
    if not MYSQL_AVAILABLE:
        raise ImportError("未安装 MySQL 客户端库，请安装: pip install pymysql 或 pip install mysql-connector-python")
    
    logger.info(f"🔧 调用工具: {tool_name}, 参数: {arguments.keys()}")
    
    if tool_name == "execute_query":
        connection = arguments.get("connection")
        sql = arguments.get("sql")
        
        if not connection:
            raise ValueError("缺少 connection 参数")
        if not sql:
            raise ValueError("缺少 sql 参数")
        
        result = execute_query(connection, sql)
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(result, ensure_ascii=False, indent=2, default=str)
                }
            ]
        }
    
    elif tool_name == "execute_update":
        connection = arguments.get("connection")
        sql = arguments.get("sql")
        
        if not connection:
            raise ValueError("缺少 connection 参数")
        if not sql:
            raise ValueError("缺少 sql 参数")
        
        result = execute_update(connection, sql)
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(result, ensure_ascii=False, indent=2, default=str)
                }
            ]
        }
    
    elif tool_name == "test_connection":
        connection = arguments.get("connection")
        
        if not connection:
            raise ValueError("缺少 connection 参数")
        
        try:
            conn = create_connection(connection)
            conn.close()
            result = {
                "success": True,
                "message": "数据库连接成功",
                "connection": {
                    "host": connection.get("host") or connection.get("ip"),
                    "port": connection.get("port", 3306),
                    "database": connection.get("database") or connection.get("db")
                }
            }
        except Exception as e:
            result = {
                "success": False,
                "message": f"数据库连接失败: {str(e)}",
                "connection": {
                    "host": connection.get("host") or connection.get("ip"),
                    "port": connection.get("port", 3306),
                    "database": connection.get("database") or connection.get("db")
                }
            }
        
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(result, ensure_ascii=False, indent=2, default=str)
                }
            ]
        }
    
    else:
        raise ValueError(f"未知工具: {tool_name}")


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
                    "name": "MySQL数据库MCP服务器",
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
            
            try:
                result = handle_tools_call(tool_name, arguments)
                return {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": result
                }
            except ImportError as e:
                logger.error(f"❌ 依赖缺失: {str(e)}")
                return _format_error_response(
                    request_id,
                    -32003,
                    "依赖缺失",
                    f"{str(e)}。请安装所需的MySQL客户端库。"
                )
            except ValueError as e:
                error_msg = str(e)
                logger.error(f"❌ 参数错误: {error_msg}")
                if "缺少" in error_msg or "需要" in error_msg:
                    return _format_error_response(
                        request_id,
                        -32602,
                        "参数错误",
                        f"{error_msg}。请检查工具调用参数是否完整。"
                    )
                elif "未知工具" in error_msg:
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
            except ConnectionError as e:
                logger.error(f"❌ 数据库连接错误: {str(e)}")
                return _format_error_response(
                    request_id,
                    -32004,
                    "数据库连接失败",
                    f"无法连接到数据库: {str(e)}。请检查连接参数（主机、端口、用户名、密码）是否正确，以及数据库服务是否运行。"
                )
            except Exception as e:
                # 检查是否是MySQL特定的错误
                error_str = str(e)
                if "Access denied" in error_str or "access denied" in error_str:
                    logger.error(f"❌ 数据库认证失败: {str(e)}")
                    return _format_error_response(
                        request_id,
                        -32005,
                        "数据库认证失败",
                        f"数据库用户名或密码错误: {str(e)}。请检查连接参数。"
                    )
                elif "Unknown database" in error_str or "unknown database" in error_str:
                    logger.error(f"❌ 数据库不存在: {str(e)}")
                    return _format_error_response(
                        request_id,
                        -32006,
                        "数据库不存在",
                        f"指定的数据库不存在: {str(e)}。请检查数据库名称是否正确。"
                    )
                elif "SQL syntax" in error_str.lower() or "syntax" in error_str.lower():
                    logger.error(f"❌ SQL语法错误: {str(e)}")
                    return _format_error_response(
                        request_id,
                        -32007,
                        "SQL语法错误",
                        f"SQL语句语法错误: {str(e)}。请检查SQL语句是否正确。"
                    )
                else:
                    logger.error(f"❌ 工具调用失败: {str(e)}", exc_info=True)
                    return _format_error_response(
                        request_id,
                        -32603,
                        "Internal error",
                        f"数据库操作失败: {str(e)}。如问题持续，请联系管理员。"
                    )
        
        else:
            return _format_error_response(
                request_id,
                -32601,
                "Method not found",
                f"未知的方法: {method}。支持的方法: initialize, notifications/initialized, tools/list, tools/call"
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
    status = "healthy" if MYSQL_AVAILABLE else "degraded"
    message = "MySQL 客户端库已安装" if MYSQL_AVAILABLE else "MySQL 客户端库未安装"
    
    return jsonify({
        "status": status,
        "service": "mysql_mcp_server",
        "mysql_available": MYSQL_AVAILABLE,
        "mysql_lib": MYSQL_LIB,
        "message": message,
        "tools": len(TOOLS)
    })


def main():
    """启动服务器"""
    port = int(os.getenv("MYSQL_MCP_SERVER_PORT", "3002"))
    host = os.getenv("MYSQL_MCP_SERVER_HOST", "0.0.0.0")
    
    logger.info("=" * 60)
    logger.info("🚀 启动 MySQL MCP 服务器")
    logger.info("=" * 60)
    logger.info(f"📍 地址: http://{host}:{port}")
    logger.info(f"💡 健康检查: http://{host}:{port}/health")
    logger.info(f"📋 可用工具: {', '.join(TOOLS.keys())}")
    
    if not MYSQL_AVAILABLE:
        logger.warning("⚠️  警告: MySQL 客户端库未安装")
        logger.warning("   请安装: pip install pymysql 或 pip install mysql-connector-python")
    else:
        logger.info(f"✅ MySQL 客户端库: {MYSQL_LIB}")
    
    logger.info("=" * 60)
    logger.info(f"🚀 正在启动服务器...")
    
    app.run(host=host, port=port, debug=False)


if __name__ == "__main__":
    main()

