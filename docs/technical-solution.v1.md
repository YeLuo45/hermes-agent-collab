# Technical Solution: Hermes Agent 团队协作增强

**Proposal ID**: P-20260419-005
**PRD Ref**: `prd.v1.md`
**Status**: draft

---

## 1. 技术栈

| 组件 | 技术选型 | 说明 |
|------|----------|------|
| 后端核心 | Python 3.10+ asyncio | 复用 Hermes 现有技术栈 |
| WebSocket | websockets / FastAPI | 实时协作通信 |
| 存储 | JSON 文件 + 文件锁 | 支持后续迁移 SQLite |
| 前端 | 独立 HTML + Vanilla JS | 不依赖 Hermes CLI |
| CLI 命令 | Click / argparse | 扩展 Hermes 现有命令 |

---

## 2. 目录结构

```
hermes/
  collaboration/              # 新增协作模块
    __init__.py
    workspace.py              # 工作区管理
    task.py                   # 任务生命周期
    agent_registry.py         # Agent Profile 管理
    skill_store.py            # 技能存储与检索
    runtime_monitor.py        # 运行时监控
    websocket_server.py       # WebSocket 服务
    events.py                 # 事件总线
  web/
    collaboration_panel.py    # 独立协作面板页面
  cli/
    workspace_cmds.py         # workspace 命令
    task_cmds.py              # task 命令
    skill_cmds.py             # skill 命令
    team_cmds.py             # team 命令
    daemon_cmds.py            # daemon 命令
```

数据存储目录：`~/.hermes/workspaces/`

```
~/.hermes/workspaces/
  {workspace_id}/
    workspace.json     # 工作区元数据
    tasks.json         # 任务列表
    skills.json        # 技能库
    agents.json        # Agent Registry
    config.json        # 工作区设置
```

---

## 3. 核心模块设计

### 3.1 工作区管理 (workspace.py)

- WorkspaceManager 类
- CRUD 操作：`list`, `create`, `switch`, `delete`
- 数据隔离：每个工作区独立目录
- 当前工作区上下文：`~/.hermes/workspaces/.current`

### 3.2 Agent Registry (agent_registry.py)

- Agent 类：id, name, role, status, capabilities, avatar
- 状态机：idle ↔ working ↔ blocked ↔ offline
- WebSocket 心跳：30s 超时判定 offline
- Agent 注册/注销事件

### 3.3 任务管理 (task.py)

- Task 类：完整字段见 PRD
- TaskManager 类
- 状态机验证：pending → claimed → in_progress → completed/failed/blocked
- 任务依赖处理：blocked_reason + depends_on
- 优先级队列：按时间 + 优先级排序

### 3.4 技能系统 (skill_store.py)

- Skill 类：id, name, description, version, commands, tags, usage_count
- SkillStore 类
- 注册/搜索/调用
- 版本管理：自动升级

### 3.5 运行时监控 (runtime_monitor.py)

- 自动检测 CLI：git, npm, python, docker, etc.
- 资源监控：CPU / 内存
- 执行日志流

### 3.6 WebSocket 服务 (websocket_server.py)

- Workspace room 隔离
- 事件类型：task.updated, agent.status, skill.created, runtime.stats
- 心跳保活

### 3.7 事件总线 (events.py)

- 单例模式
- 订阅/发布机制
- WebSocket 广播

---

## 4. CLI 命令

| 命令 | 操作 |
|------|------|
| `hermes workspace list` | 列出所有工作区 |
| `hermes workspace create <name>` | 创建工作区 |
| `hermes workspace switch <id>` | 切换工作区 |
| `hermes workspace delete <id>` | 删除工作区 |
| `hermes task list` | 列出当前工作区任务 |
| `hermes task create <title>` | 创建任务 |
| `hermes task claim <id>` | 认领任务 |
| `hermes task complete <id>` | 完成任务 |
| `hermes task status <id> <status>` | 更新状态 |
| `hermes skill register <name>` | 注册技能 |
| `hermes skill list` | 列出技能 |
| `hermes skill search <query>` | 搜索技能 |
| `hermes team status` | 显示团队状态 |
| `hermes daemon start` | 启动守护进程 |
| `hermes daemon stop` | 停止守护进程 |
| `hermes daemon status` | 查看状态 |

---

## 5. 独立 Web 面板

- 路径：`/collaboration` 或独立端口 3101
- 功能：
  - 工作区选择器
  - Agent 状态面板
  - 任务看板（卡片/列表视图）
  - 技能库浏览
  - 实时 WebSocket 更新
- 认证：复用 Hermes 现有认证机制

---

## 6. 数据迁移策略

- v1：JSON 文件存储
- 预留 SQLite 迁移接口
- 文件锁保证并发安全

---

## 7. 回滚机制

- proposals-manager 已打 tag v1.0.0
- 回滚方式：`git checkout v1.0.0 && git push --force origin gh-pages`
- hermes-agent 开发过程中的中间版本不上线，只在完成后统一部署

---

## 8. 开发顺序

1. 基础数据模型和存储
2. 工作区 CRUD
3. Agent Profile + 状态管理
4. 任务 CRUD + 状态机
5. WebSocket 服务
6. 独立 Web 面板
7. 技能系统
8. CLI 命令
9. 运行时监控

---

*本文档待确认后执行开发。*