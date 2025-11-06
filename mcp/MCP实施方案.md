# MCP
## 流程
AI需要调用MCP服务 → 查询指定MCP服务器的信息 → AI调用MCP服务
## 添加/删除MCP服务
学习**cursor**，通过更改**mcp.json**来实现
```
{
  "mcpServers": {
    "AliyunBailianMCP_WebSearch": {
      "type": "sse",
      "url": "https://dashscope.aliyuncs.com/api/v1/mcps/WebSearch/sse",
      "headers": {
        "Authorization": "Bearer sk-520dbcf9622a42c2a39b851b9e636d1b"
      }
    },
      "12306-mcp": {
      "type": "streamable_http",
      "url": "https://mcp.api-inference.modelscope.net/bc61aa37759b47/mcp"
    }
  }
}
```
在这个示例中，引入了阿里云的Web Search、12306票务查询服务，如果需要禁用，只需要在**mcp.json**删除对应的MCP服务器信息即可

## 服务发现/使用
1.当程序启动后，会读取本地的mcp.json，获得需要启用的mcp服务器的列表
2.然后通过"initialize"调用它们，获得它们的具体信息，调用失败的将被忽略，至此与**可用**的MCP服务器建立了连接
3.将所有**可用**的MCP服务器的详细信息存入**MongoDB**(在此之前需要清空数据库的数据，cursor更改MCP的配置后也是需要重启才能生效的)，生成**server_id**，再由LLM生成**工具概述**，最后汇总成一份“工具概述清单”
示例如下
```
以下为可用的工具，description里包含了功能，当你需要调用时，构造请求发送server_id给manager_server
"mcp_servers":[
    {
        "description":修改、创建、删除文件,
        "server_id":"file_mcp_server"
    }
]
```
4.**manager_server**负责通过**server_id**去**MongoDB**查询MCP服务器的完整信息，包括url、parameters等
5.当用户输入“我需要创建一个markdown文档”时，会根据**server_id**去调用**manager_server**，进而获得**file_mcp_server**的完整信息，再去调用**file_mcp_server**里的"**create_file**"工具
## 优劣势对比分析
|  | 实现方法 | 优势 | 劣势 |
| - | - | - | - |
| *方案A* | 将tools的信息全部存储到上下文 |  | MCP可能会占用大量token |
| *方案B* | 将tools的概述存储到上下文，需要调用的时候再去文档数据库查完整的信息 | MCP占用更少的token | 网络延迟更高 |
