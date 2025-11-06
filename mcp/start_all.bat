@echo off
chcp 65001 >nul
echo ========================================
echo 启动所有 MCP 服务器和 LangGraph
echo ========================================
echo.

cd /d "%~dp0"

REM 检查Python是否安装
python --version >nul 2>&1
if errorlevel 1 (
    echo ❌ 错误: 未找到 Python，请先安装 Python
    pause
    exit /b 1
)

echo 📋 正在启动 MCP 服务器...
echo.

REM 启动文件操作服务器 (端口 3000)
echo 🚀 启动文件操作服务器 (端口 3000)...
start "MCP - 文件服务器 (3000)" cmd /k "cd /d %~dp0 && python file_mcp_server.py"
timeout /t 2 /nobreak >nul

REM 启动时间服务器 (端口 3001)
echo 🚀 启动时间服务器 (端口 3001)...
start "MCP - 时间服务器 (3001)" cmd /k "cd /d %~dp0 && python time_mcp_server.py"
timeout /t 2 /nobreak >nul

REM 启动MySQL数据库服务器 (端口 3002)
echo 🚀 启动MySQL数据库服务器 (端口 3002)...
start "MCP - MySQL服务器 (3002)" cmd /k "cd /d %~dp0 && python mysql_mcp_server.py"
timeout /t 2 /nobreak >nul

REM 启动MongoDB MCP服务器 (端口 3003)
echo 🚀 启动MongoDB MCP服务器 (端口 3003)...
start "MCP - MongoDB服务器 (3003)" cmd /k "cd /d %~dp0 && python mongo_db_mcp_server.py"
timeout /t 2 /nobreak >nul

REM 可选：启动Vocaloid网站服务器 (端口 3004) - 配置中默认禁用
REM echo 🚀 启动Vocaloid网站服务器 (端口 3004)...
REM start "MCP - Vocaloid服务器 (3004)" cmd /k "cd /d %~dp0 && python vocaloid_website_mcp_server.py"
REM timeout /t 2 /nobreak >nul

echo.
echo ⏳ 等待服务器启动完成 (5秒)...
timeout /t 5 /nobreak >nul

echo.
echo ========================================
echo 启动 LangGraph Agent
echo ========================================
echo 💡 提示: 关闭此窗口将退出 LangGraph，但 MCP 服务器将继续运行
echo 💡 要关闭所有服务器，请关闭对应的服务器窗口
echo ========================================
echo.

REM 启动LangGraph
python langgraph_integration.py

echo.
echo ========================================
echo LangGraph 已退出
echo ========================================
echo 💡 提示: MCP 服务器仍在运行，请手动关闭对应的服务器窗口以停止它们
echo.
pause

