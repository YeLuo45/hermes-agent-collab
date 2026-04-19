# PRD: Hermes Agent 团队协作增强

**Proposal ID**: P-20260419-005
**Title**: Hermes Agent 团队协作增强
**Owner**: 小墨
**Created**: 2026-04-19
**Status**: prd_pending_confirmation

---

## 1. Overview / 背景

Hermes Agent 目前是单 Agent 运行模式，主要服务于个人用户。为支持团队协作场景，需要构建一套完整的任务协作框架，使多个 Agent 和人类用户能够协同完成复杂任务。

核心参考：参考 [Multica](https://github.com/YeLuo45/multica) 集合到 Hermes，实现团队级别的任务协作、技能共享和多工作区管理。

---

## 2. Goals / 目标

- **Agent 即队友**：每个 Agent 有独立 Profile，在任务面板显示，参与对话，报告阻塞，主动更新状态
- **自主执行**：完整的任务生命周期管理（入队、认领、开始、完成/失败），支持 WebSocket 实时进度流
- **可复用技能**：每个解决方案变成可复用技能，全团队共享，技能随使用不断累积
- **统一运行时**：统一管理所有计算环境，本地 Daemon 模式，自动检测可用 CLI，实时监控
- **多工作区**：按团队组织工作区，工作区级别数据隔离，每个工作区有独立的 Agent、Issue 和设置

---

## 3. Non-Goals / 非目标

- 第一期不支持权限体系（权限体系作为后续迭代）
- 第一期不支持远程执行（如 SSH 到其他机器）
- 第一期不支持云端同步，仅本地运行
- 不完全重写，基于现有 Hermes 框架扩展

---

## 4. Core Features / 核心功能

### 4.1 Agent Profile System

每个 Agent 拥有独立 Profile，包含：

- `agent_id`: 唯一标识符（UUID）
- `name`: 显示名称
- `role`: 角色类型（developer / pm / qa / custom）
- `status`: 当前状态（idle / working / blocked / offline）
- `capabilities`: 技能列表
- `avatar`: 头像 URI（可选）

状态自动同步到任务面板，人类用户可查看所有在线 Agent 状态。

### 4.2 Task Lifecycle Management

任务状态机：

```
pending → claimed → in_progress → completed / failed / blocked
```

- **pending**: 任务入队，等待认领
- **claimed**: 有 Agent 认领，尚未开始
- **in_progress**: 执行中
- **completed**: 成功完成
- **failed**: 执行失败
- **blocked**: 被阻塞（等待依赖或资源）

任务数据结构：

```json
{
  "task_id": "uuid",
  "title": "string",
  "description": "string",
  "status": "pending|claimed|in_progress|completed|failed|blocked",
  "assignee": "agent_id | null",
  "creator": "agent_id",
  "created_at": "ISO8601",
  "updated_at": "ISO8601",
  "blocked_reason": "string | null",
  "depends_on": ["task_id"],
  "priority": "low | medium | high | critical",
  "workspace_id": "uuid"
}
```

### 4.3 WebSocket Real-time Progress

支持 WebSocket 实时推送：

- 任务状态变更事件
- Agent 状态变更事件
- 任务执行日志流
- 阻塞/解除阻塞通知

WebSocket 连接按工作区隔离，认证后加入对应 room。

### 4.4 Skill System / 技能系统

技能定义：

```json
{
  "skill_id": "uuid",
  "name": "string",
  "description": "string",
  "version": "semver",
  "author": "agent_id",
  "created_at": "ISO8601",
  "updated_at": "ISO8601",
  "commands": ["string"],
  "tags": ["string"],
  "usage_count": 0,
  "workspace_id": "uuid"
}
```

技能来源：
- 任务完成时，提取解决方案为可复用技能
- Agent 手动注册技能
- 团队成员共享导入

### 4.5 Unified Runtime / 统一运行时

本地 Daemon 模式：

- 自动检测系统中可用的 CLI 工具（git, npm, python, docker 等）
- 实时监控资源使用（CPU / 内存）
- 任务在隔离环境中执行
- 执行日志实时流推送

### 4.6 Multi-Workspace / 多工作区

工作区数据结构：

```json
{
  "workspace_id": "uuid",
  "name": "string",
  "description": "string",
  "created_at": "ISO8601",
  "agents": ["agent_id"],
  "settings": {
    "default_agent": "agent_id",
    "notifications_enabled": true
  }
}
```

- 数据隔离：每个工作区的任务、技能、配置完全隔离
- 工作区列表 API 支持列举当前用户可访问的工作区

---

## 5. Data Model / 数据模型

### 5.1 Storage

使用 JSON 文件存储，类 Multica board 的简化实现：

```
~/.hermes/workspaces/
  {workspace_id}/
    workspace.json        # 工作区元数据
    tasks.json            # 任务列表
    skills.json           # 技能库
    agents.json           # Agent Registry
    config.json           # 工作区设置
```

### 5.2 Key Entities

| Entity | File | Key Field |
|--------|------|-----------|
| Workspace | workspace.json | workspace_id |
| Task | tasks.json | task_id |
| Skill | skills.json | skill_id |
| Agent | agents.json | agent_id |

---

## 6. Architecture / 架构

### 6.1 Module Structure

```
hermes/
  collaboration/           # 新增：协作模块
    __init__.py
    workspace.py           # 工作区管理
    task.py                # 任务生命周期
    agent_registry.py      # Agent Profile 管理
    skill_store.py         # 技能存储与检索
    runtime_monitor.py     # 运行时监控
    websocket_server.py    # WebSocket 服务
  web/                     # 现有 web 模块
    collaboration_ui.py     # 新增：协作面板 UI
```

### 6.2 WebSocket Protocol

事件格式：

```json
{
  "event": "task.updated | agent.status | skill.created | runtime.stats",
  "workspace_id": "uuid",
  "payload": {},
  "timestamp": "ISO8601"
}
```

### 6.3 CLI Integration

新增命令：

- `hermes workspace list|create|switch|delete`
- `hermes task list|create|claim|complete|status`
- `hermes skill register|list|search|invoke`
- `hermes team status|invite`
- `hermes daemon start|stop|status`

---

## 7. Technical Approach / 技术方案

### 7.1 Web Framework

WebSocket 使用 Python 标准库 `asyncio` + `websockets`（或 FastAPI + WebSocket）。

### 7.2 Persistence

使用 JSON 文件 + 文件锁，支持后续迁移到 SQLite。

### 7.3 Real-time Updates

- WebSocket 服务独立进程（或集成到 gateway）
- 任务状态变更通过事件总线广播

### 7.4 Skill Invocation

技能以 Python 函数或 Shell 脚本形式存储，通过标准输入/输出交互。

---

## 8. Implementation Phases / 实施阶段

### Phase 1: 基础框架（1-2 周）

- 工作区 CRUD
- Agent Profile 系统
- 任务 CRUD + 状态机
- 基础 CLI 命令

### Phase 2: 实时协作（1-2 周）

- WebSocket 服务
- 实时任务状态推送
- 任务面板 Web UI

### Phase 3: 技能系统（1-2 周）

- 技能注册与存储
- 技能搜索与调用
- 技能使用统计

### Phase 4: 运行时监控（1 周）

- CLI 自动检测
- 资源使用监控
- 执行日志流

---

## 9. Risks and Mitigations / 风险与缓解

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| JSON 文件并发写入冲突 | 数据损坏 | 使用文件锁，WebSocket 操作串行化 |
| WebSocket 连接数上限 | 扩展性 | 设计为无状态，可水平扩展 |
| 技能安全风险 | 执行恶意代码 | 技能沙箱隔离，Approval 机制复用 |
| 与现有 Hermes 冲突 | 破坏现有功能 | 基于现有框架扩展，充分测试 |

---

## 10. Dependencies / 依赖

- Python 3.10+
- asyncio / websockets（或 FastAPI）
- 复用现有 Hermes 的 approval、delegate 等机制
- 复用 hermes_state.py 的 session 管理

---

## 11. Metrics / 成功指标

- Agent 状态更新延迟 < 1s
- 任务状态变更 WebSocket 推送 < 500ms
- CLI 命令响应时间 < 200ms
- 支持同时在线 Agent 数 >= 10

---

## 12. Open Questions / 待确认

~~1. Web UI 是独立页面还是集成到现有 Hermes CLI/Web？~~
~~2. 技能版本管理策略（自动升级 vs 手动确认）？~~
~~3. 任务优先级如何影响调度顺序？~~

**已确认：**
1. **Web UI** — 独立页面，不集成到现有 Hermes CLI/Web
2. **技能版本** — 自动升级
3. **任务调度** — 支持并行，默认按时间排序（时间越早优先级越高），支持手动设置优先级（值越高优先级越高）

---

*本文档为 PRD 初稿，等待确认后进入技术方案阶段。*
