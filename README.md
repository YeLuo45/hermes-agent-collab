# Hermes Agent 团队协作增强

**Proposal ID**: P-20260419-005
**Status**: in_dev
**GitHub Repo**: https://github.com/YeLuo45/hermes-agent

## 项目简介

为 Hermes Agent 添加团队协作能力，支持多 Agent 协同完成任务，支持实时 WebSocket 推送和独立 Web 协作面板。

核心功能：
- **多工作区**：按团队组织工作区，数据隔离
- **Agent 即队友**：Agent Profile 系统，状态实时同步
- **任务协作**：完整任务生命周期管理（pending→claimed→in_progress→completed/failed/blocked）
- **WebSocket 实时推送**：任务/Agent 状态变更实时广播
- **技能系统**：可复用技能库，团队共享
- **统一运行时**：CLI 自动检测，资源监控

## 目录结构

```
hermes-agent/
├── collaboration/           # 协作模块核心代码
│   ├── __init__.py         # 模块导出
│   ├── __main__.py         # CLI 入口
│   ├── models.py           # 数据模型（Agent/Task/Skill/Workspace）
│   ├── storage.py          # JSON 存储层（文件锁）
│   ├── workspace.py        # 工作区管理
│   ├── agent_registry.py   # Agent Profile 管理
│   ├── task.py             # 任务生命周期
│   ├── skill_system.py     # 技能系统
│   ├── events.py           # 事件总线
│   ├── websocket_server.py # WebSocket 服务
│   ├── collab_api.py       # FastAPI REST API
│   ├── server.py           # 独立服务器
│   ├── cli.py              # CLI 命令
│   ├── monitor.py          # 运行时监控
│   └── web/                # 独立 Web UI（构建产物）
└── docs/                   # 文档
    ├── prd.v1.md
    └── technical-solution.v1.md
```

## 运行方式

### 1. 独立服务器模式（推荐）

```bash
cd ~/.hermes/workspace-dev/proposals/hermes-agent

# 启动协作服务器（REST API + WebSocket + Web UI）
python3 -m collaboration server --port 9119 --host 0.0.0.0

# 访问 Web UI
open http://127.0.0.1:9119
```

### 2. CLI 模式

```bash
# 工作区管理
python3 -m collaboration workspace list
python3 -m collaboration workspace create my-team
python3 -m collaboration workspace switch <workspace_id>

# Agent 管理
python3 -m collaboration agent list
python3 -m collaboration agent register --name "DevBot" --role developer

# 任务管理
python3 -m collaboration task list
python3 -m collaboration task create "实现登录功能"
python3 -m collaboration task claim <task_id>
python3 -m collaboration task complete <task_id>

# 技能管理
python3 -m collaboration skill list
python3 -m collaboration skill register --name "debug-react" --commands "npm run debug"

# 运行时监控
python3 -m collaboration monitor health
python3 -m collaboration monitor status
```

### 3. API 端点

```
REST API: http://127.0.0.1:9119/api/collab/
WebSocket: ws://127.0.0.1:9119/api/collab/ws?workspace_id=<id>
```

主要端点：
- `GET /api/collab/workspaces` - 列出工作区
- `POST /api/collab/workspaces` - 创建工作区
- `GET /api/collab/agents` - 列出 Agent
- `POST /api/collab/tasks` - 创建任务
- `PATCH /api/collab/tasks/{id}/claim` - 认领任务
- `GET /api/collab/skills` - 列出技能

## 数据存储

数据存储在 `~/.hermes/workspaces/` 目录下，每个工作区独立：

```
~/.hermes/workspaces/
  {workspace_id}/
    workspace.json     # 工作区元数据
    tasks.json         # 任务列表
    skills.json        # 技能库
    agents.json        # Agent Registry
    config.json        # 工作区设置
```

## 技术栈

- Python 3.10+ asyncio
- FastAPI + websockets
- JSON 文件存储 + fcntl 文件锁
- React + TypeScript + TailwindCSS（Web UI）

## 回滚说明

proposals-manager 已打 tag v1.0.0。回滚命令：
```bash
cd ~/.hermes/workspace-dev/proposals/proposals-manager
git checkout v1.0.0
git push --force origin gh-pages
```

hermes-agent 项目本身无版本限制，可随时重置。
