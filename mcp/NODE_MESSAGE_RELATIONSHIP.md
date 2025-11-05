# Node 和消息的关系

## 核心概念

在 LangGraph 中，**Node（节点）** 和 **Message（消息）** 通过 **State（状态）** 连接：

```
State (状态容器)
  └── messages (消息列表)
        ├── SystemMessage
        ├── HumanMessage
        ├── AIMessage
        └── ToolMessage
```

## 关系图

```
┌─────────────────────────────────────────────────────────┐
│                    AgentState                           │
│  ┌──────────────────────────────────────────────────┐  │
│  │  messages: [Message1, Message2, Message3, ...]  │  │
│  └──────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
                    ↑              ↓
                    │              │
         Node 读取消息    Node 生成新消息
                    │              │
         ┌──────────┴──────────────┴──────────┐
         │                                     │
    ┌────▼────┐                          ┌────▼────┐
    │ chat_node│                          │tool_node│
    │          │                          │         │
    │ 1. 读取   │                          │ 1. 读取  │
    │    state["messages"]                │   tool_calls
    │                                    │         │
    │ 2. 添加   │                          │ 2. 执行  │
    │    SystemMessage                   │   工具    │
    │                                    │         │
    │ 3. 调用   │                          │ 3. 生成  │
    │    LLM                             │   ToolMessage
    │                                    │         │
    │ 4. 返回   │                          │ 4. 返回  │
    │    {"messages": [AIMessage]}      │   {"messages": [...]}
    └──────────┘                          └─────────┘
```

## 详细流程

### 1. 状态定义

```python
class AgentState(TypedDict):
    """Agent状态定义"""
    messages: Annotated[Sequence[BaseMessage], operator.add]
    #                      ↑                        ↑
    #                    消息列表             自动合并机制
```

**关键点：**
- `messages` 是状态的一部分
- `Annotated[Sequence[BaseMessage], operator.add]` 表示消息会被自动追加合并

### 2. Node 读取消息

每个 node 函数接收 `state` 作为参数，可以读取消息：

```python
def chat_node(state: AgentState):
    """Chat节点：处理对话，决定下一步行动"""
    messages = state["messages"]  # ← 从状态中读取消息
    # messages 是完整的消息历史
```

### 3. Node 处理消息

Node 可以：
- **读取**历史消息
- **添加**新的 SystemMessage（临时，不存入状态）
- **调用** LLM 处理消息
- **生成**新的消息

```python
def chat_node(state: AgentState):
    messages = state["messages"]  # 读取历史消息
    
    # 添加系统消息（临时，用于本次 LLM 调用）
    system_message = SystemMessage(content=tools_description)
    agent_messages = [system_message] + list(messages)
    
    # 调用 LLM（传入消息列表）
    response = llm_with_tools.invoke(agent_messages)
    
    # 返回新生成的消息
    return {"messages": [response]}  # ← 只返回新消息
```

### 4. Node 返回新消息

Node 返回的字典包含**新生成的消息**：

```python
return {"messages": [response]}
#      ↑              ↑
#    状态字段      新消息列表（AIMessage）
```

**重要：**
- Node 只返回**新增**的消息
- **不需要**返回所有历史消息
- LangGraph 会自动合并（因为使用了 `operator.add`）

### 5. LangGraph 自动合并

由于使用了 `Annotated[Sequence[BaseMessage], operator.add]`：

```python
# Node 返回前
state = {
    "messages": [msg1, msg2, msg3]
}

# Node 返回
return {"messages": [msg4]}

# LangGraph 自动合并后
new_state = {
    "messages": [msg1, msg2, msg3, msg4]  # ← 自动追加
}
```

## 在你的代码中的具体实现

### chat_node（聊天节点）

```python
def chat_node(state: AgentState):
    # 1. 读取消息
    messages = state["messages"]
    
    # 2. 添加系统消息（临时）
    system_message = SystemMessage(content=tools_description)
    agent_messages = [system_message] + list(messages)
    
    # 3. 调用 LLM
    response = llm_with_tools.invoke(agent_messages)
    
    # 4. 返回新消息（AIMessage）
    return {"messages": [response]}
```

**处理流程：**
```
输入: state["messages"] = [HumanMessage("读取文件")]
  ↓
添加 SystemMessage（临时）
  ↓
调用 LLM → 生成 AIMessage(tool_calls=[read_file])
  ↓
返回: {"messages": [AIMessage(tool_calls=[...])]}
  ↓
LangGraph 合并: messages = [HumanMessage, AIMessage(tool_calls)]
```

### tool_node（工具节点）

```python
tool_node = ToolNode(dynamic_tools)
# ToolNode 内部会：
# 1. 读取最后一条消息的 tool_calls
# 2. 执行工具
# 3. 生成 ToolMessage
# 4. 返回 {"messages": [ToolMessage, ...]}
```

**处理流程：**
```
输入: state["messages"] = [HumanMessage, AIMessage(tool_calls=[read_file])]
  ↓
ToolNode 读取 tool_calls
  ↓
执行工具 → 获取结果
  ↓
生成 ToolMessage(content="文件内容...", tool_call_id="call_123")
  ↓
返回: {"messages": [ToolMessage]}
  ↓
LangGraph 合并: messages = [HumanMessage, AIMessage, ToolMessage]
```

### should_continue（条件判断）

```python
def should_continue(state: AgentState):
    messages = state["messages"]  # 读取消息
    last_message = messages[-1]   # 检查最后一条消息
    
    # 根据消息类型决定路由
    if last_message 有 tool_calls:
        return "tools"  # 路由到 tool_node
    elif last_message 是 ToolMessage:
        return "chat"   # 路由到 chat_node
    else:
        return END      # 结束
```

## 完整消息流程示例

```
初始状态:
  messages: [HumanMessage("读取文件 test.txt")]

第1步: chat_node 执行
  ├─ 读取: [HumanMessage("读取文件 test.txt")]
  ├─ 添加 SystemMessage（临时）
  ├─ 调用 LLM
  └─ 返回: {"messages": [AIMessage(tool_calls=[read_file])]}
  
合并后:
  messages: [HumanMessage, AIMessage(tool_calls)]

第2步: should_continue 判断
  ├─ 检查最后一条消息
  ├─ 发现 tool_calls
  └─ 路由到: "tools"

第3步: tool_node 执行
  ├─ 读取: messages[-1].tool_calls
  ├─ 执行工具: read_file("test.txt")
  └─ 返回: {"messages": [ToolMessage("文件内容：...")]}
  
合并后:
  messages: [HumanMessage, AIMessage, ToolMessage]

第4步: should_continue 判断
  ├─ 检查最后一条消息
  ├─ 发现是 ToolMessage
  └─ 路由到: "chat"

第5步: chat_node 执行
  ├─ 读取: [HumanMessage, AIMessage, ToolMessage]
  ├─ 添加 SystemMessage（临时）
  ├─ 调用 LLM（现在有工具结果了）
  └─ 返回: {"messages": [AIMessage("文件内容如下：...")]}
  
合并后:
  messages: [HumanMessage, AIMessage, ToolMessage, AIMessage]
```

## 关键要点

### 1. 消息是共享的
- 所有 node 共享同一个 `state["messages"]`
- 消息历史在节点间传递

### 2. Node 只返回新消息
- Node 不需要返回所有历史消息
- 只返回本次生成的新消息
- LangGraph 自动合并

### 3. SystemMessage 是临时的
- 在 `chat_node` 中添加的 SystemMessage 只用于本次 LLM 调用
- **不会**被添加到 `state["messages"]` 中
- 每次调用 chat_node 都会重新添加

### 4. 消息顺序很重要
- 消息按时间顺序排列
- 最后一条消息通常决定下一步操作

### 5. 消息类型决定路由
- `AIMessage` 含 `tool_calls` → 路由到 `tool_node`
- `ToolMessage` → 路由回 `chat_node`
- 普通 `AIMessage` → 结束

## 常见问题

### Q: Node 可以修改历史消息吗？
A: 可以，但不推荐。最好只返回新消息，让 LangGraph 自动合并。

### Q: SystemMessage 会被保存到状态吗？
A: 不会。只有 node 返回的消息才会被合并到状态中。

### Q: 多个 node 可以同时访问消息吗？
A: 不会。LangGraph 是顺序执行的，一个 node 执行完后才会执行下一个。

### Q: 如何清除消息历史？
A: 可以返回一个新的消息列表，或者修改状态管理逻辑。

## 总结

| 方面 | 说明 |
|------|------|
| **Node 读取** | 从 `state["messages"]` 读取消息历史 |
| **Node 处理** | 添加临时 SystemMessage，调用 LLM/工具 |
| **Node 返回** | 只返回新生成的消息 |
| **LangGraph 合并** | 自动将新消息追加到历史消息中 |
| **消息共享** | 所有 node 共享同一个消息列表 |
| **路由决策** | 基于最后一条消息的类型和内容 |

Node 和消息的关系是：**Node 读取消息 → 处理消息 → 生成新消息 → LangGraph 自动合并**

