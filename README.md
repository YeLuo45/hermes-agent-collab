# Hermes Agent 团队协作增强

**Proposal ID**: P-20260419-005
**Status**: accepted (Phase 1-3)
**GitHub Repo**: https://github.com/YeLuo45/hermes-agent-collab
**Web UI**: https://yeluo45.github.io/hermes-agent-collab/

## 项目简介

为 Hermes Agent 添加团队协作能力，支持多 Agent 协同完成任务，支持实时 WebSocket 推送和独立 Web 协作面板。

核心功能：
- **多工作区**：按团队组织工作区，数据隔离
- **Agent 即队友**：Agent Profile 系统，状态实时同步
- **任务协作**：完整任务生命周期管理（pending→in_progress→completed/failed/blocked）
- **WebSocket 实时推送**：任务/Agent 状态变更实时广播
- **技能系统**：可复用技能库，团队共享
- **统一运行时**：CLI 一键调用，资源监控

## 目录结构

```
hermes-agent/
├── docs/                   # 文档
│   ├── prd.v1.md
│   └── technical-solution.v1.md
└── （协作模块代码位于 ~/.hermes/collab/）
```

协作模块实际安装位置：`~/.hermes/collab/`

## 运行方式

### 前置要求

`collab` 命令已通过 `~/bin/collab` 包装脚本提供。确保 `~/bin` 在 PATH 中（新终端自动生效，或手动 `source ~/.bash_aliases`）。

### 1. 独立服务器模式（推荐）

```bash
# 启动协作服务器（REST API + WebSocket + Web UI）
collab server

# 访问 Web UI
open http://127.0.0.1:9119
```

### 2. CLI 模式

```bash
# 工作区管理
collab workspace list
collab workspace create --name "my-team" --owner agent-1

# Agent 管理
collab agent list
collab agent register --name "DevBot" --role developer --workspace ws-xxx

# 任务管理
collab task list --workspace ws-xxx
collab task create --title "实现登录功能" --workspace ws-xxx
collab task update <task_id> start --agent-id agent-1
collab task update <task_id> complete

# 技能管理
collab skill list
collab skill create --name "debug-react" --category devops

# 运行时监控
collab monitor health
collab monitor events --limit 20
collab monitor stats
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
