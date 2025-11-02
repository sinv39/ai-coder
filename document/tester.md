# 调试器（Debugger）

具备自动化调试与修复能力的工程级系统组件，能够根据测试用例、功能描述或错误现象，在真实工程项目上下文中自动定位缺陷、递归分析调用链，并安全地生成、验证和返回多文件协同修复方案。仅当修复成功时返回修改后的代码；若无法修复，则返回结构化诊断信息，支持人机协同决策。

---

## 设计原则

- **工程感知**：深度理解项目结构、依赖、构建与测试配置。
- **安全修复**：源码只读保护，修复在隔离副本中验证，支持影响分析。
- **递归协同**：支持跨文件调用链追踪与多文件协同修复。
- **高效复用**：一个工程一个调试容器，依赖仅安装一次。
- **人机协同**：提供候选修复、半自动模式与可审计轨迹。

> **注**：版本管理（如补丁快照、回滚、Git 集成）由外部系统负责，本组件不实现。

---

## 总体架构

```
Interface
   ↓
Project-Scoped Debugger Container (长期运行，工程绑定)
   ├── 只读挂载：/project-ro ← project_root
   ├── 可写副本：/project-ws ← .debugger/workspace/project/
   └── Debugger Backend
          ├── 入口定位器
          ├── 行为解析器（测试/功能描述）
          ├── 递归分析引擎（调用图 + 符号追踪）
          ├── 多文件修复生成器
          ├── 安全验证器（类型检查/影响分析）
          └── 结果决策器
```

---

## 接口定义（RESTful API）

### 请求参数

| 字段 | 类型 | 必需 | 说明 |
|------|------|------|------|
| `project_root` | string | ✅ | 工程绝对路径（如 `/workspace/my-app`） |
| `test_cases` | array | ⚠️ | 显式测试用例（输入/输出对） |
| `functionality` | string | ⚠️ | 自然语言功能描述（如 “返回两数之和”） |
| `entry_point` | string | ❌ | 调试入口文件（未提供则自动推断） |
| `code_snippet` | string | ❌ | 引导性代码片段（用于定位） |
| `language` | string | ❌ | 语言及版本（自动推断优先） |
| `timeout` | integer | ❌ | 超时（秒，默认 60） |
| `enable_recursive_fix` | boolean | ❌ | 启用递归跨文件修复（默认 `true`） |

> `test_cases` 与 `functionality` 至少提供其一。

### 响应策略

- **修复成功**：仅返回修复结果（无调试细节）。
- **修复失败**：返回完整诊断，含递归路径、生成测试、建议修复。
- **多方案场景**：返回候选修复列表（当启用人机协同模式）。

---

## 工程级执行环境

### 容器与目录结构

- **容器生命周期**：每个 `project_root` 绑定一个长期运行的专属容器。
- **挂载策略**：
    - `project_root` → 容器内 `/project-ro`（**只读**）
    - `project_root/.debugger/workspace/` → 容器内 `/project-ws`（**可写**）
- **目录示例**：
  ```
  /workspace/my-app/
  ├── src/
  ├── pyproject.toml
  └── .debugger/
      ├── config.yaml          # 调试策略配置
      ├── container.id
      └── workspace/
          ├── project/         # 可写工程副本（用于修复验证）
          └── symbol_index/    # 调用图与符号缓存（可选）
  ```

### 依赖与构建

- 首次调试时，根据工程类型自动执行标准构建命令：
    - Python (Poetry): `poetry install --no-root`
    - Node.js: `npm ci`
    - Go: `go mod download && go build ./...`
- 后续调试复用已安装依赖，仅当依赖文件变更时更新。

---

## 核心能力详解

### 1. 递归跨文件修复

- **调用链追踪**：从测试失败点出发，静态分析（AST/import） + 动态 trace（可选）构建调用图。
- **多文件补丁集**：生成涉及多个文件的协同修复方案。
- **整体验证**：在 `/project-ws` 中应用全部补丁后运行完整测试。

### 2. 工程元信息感知

- 自动识别：
    - 语言版本（`.nvmrc`, `go.mod`, `pyproject.toml`）
    - 测试框架（`pytest`, `jest`, `go test`）
    - 构建工具（Poetry, npm, Make）
- 复用工程原生命令，确保环境一致性。

### 3. 修复安全与影响分析

- **影响扫描**：若修改公共函数，静态分析所有调用者。
- **契约检查**：修复后运行类型检查（`mypy`, `tsc`, `go vet`）。
- **高风险操作拦截**：
    - 禁止引入新外部依赖（默认）
    - 禁止修改 API 签名（如删除函数参数）

### 4. 人机协同修复

- **候选修复列表**：当存在多个合理方案时，返回带风险评级的选项。
- **交互式选择 API**：支持人工选择后验证。
- **配置控制**：通过 `.debugger/config.yaml` 启用“总是返回候选”模式。

### 5. 安全与范围控制

- **路径白/黑名单**：通过配置限制可修复文件范围。
- **敏感内容过滤**：拒绝处理含密钥、token 的文件。
- **资源隔离**：无网络、只读源码、配额限制。

---

## 输出示例

### 成功（多文件修复）

```json
{
  "status": "fixed",
  "fixed_files": {
    "src/math.py": "def add(a, b):\n    return a + b",
    "src/utils.py": "def safe_div(x, y):\n    if y == 0: return None\n    return x / y"
  },
  "patch_set": [
    { "file": "src/math.py", "patch": "@@ -1 +1 @@\n-def add(a, b): return a - b\n+def add(a, b): return a + b" },
    { "file": "src/utils.py", "patch": "@@ -2 +2,3 @@\n-def safe_div(x, y):\n-    return x / y\n+def safe_div(x, y):\n+    if y == 0: return None\n+    return x / y" }
  ]
}
```

### 失败（含递归诊断）

```json
{
  "status": "unfixable",
  "diagnosis": "Error originates in utils/math.py:first_nonzero, not in entry point.",
  "call_path": ["api/cart.py → services/pricing.py → utils/math.py"],
  "generated_test_cases": [{ "input": [], "output": null }],
  "error_trace": "IndexError: list index out of range",
  "suggested_fixes": [
    "Add empty list check in utils/math.py:first_nonzero"
  ]
}
```

### 候选修复（人机协同模式）

```json
{
  "status": "candidates",
  "candidates": [
    {
      "id": "fix-1",
      "description": "Return 0 for empty input",
      "risk": "low",
      "files": { "src/utils.py": "..." }
    },
    {
      "id": "fix-2",
      "description": "Raise ValueError on empty input",
      "risk": "high",
      "files": { "src/utils.py": "..." }
    }
  ]
}
```

---

## 配置文件：`.debugger/config.yaml`（可选）

```yaml
# 工程调试策略
language: python3.11
project_type: poetry

entry_resolution:
  strategy: auto
  test_patterns: ["tests/**/test_*.py"]

recursive_fix:
  enabled: true
  max_depth: 6
  allowed_paths: ["src/", "lib/"]
  denied_paths: ["legacy/", "secrets/"]

build:
  cmd: "poetry install --no-root"

test:
  framework: pytest
  enable_type_check: true

safety:
  allow_new_imports: false
  enable_impact_analysis: true

human_in_the_loop:
  prefer_candidates: false
```

---

## 优势总结

| 维度 | 能力 | 价值 |
|------|------|------|
| **准确性** | 工程元感知 + 递归分析 | 修得对，不治标 |
| **安全性** | 影响分析 + 范围控制 | 修得稳，无副作用 |
| **灵活性** | 候选修复 + 半自动 | 修得准，适配业务 |
| **效率** | 依赖缓存 + 增量索引 | 修得快，低开销 |

> 该调试器专为 **Code Agent 在复杂工程项目中实现端到端自动化修复** 而设计，是连接“错误现象”与“可靠修复”的智能工程桥梁。版本管理、补丁持久化与回滚等能力由外部系统统一处理，本组件聚焦于**安全、准确、高效的修复生成与验证**。