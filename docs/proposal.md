# Proposal Intake Template

## Basic Information

- `Proposal ID`: P-20260419-005
- `Title`: Hermes Agent 团队协作增强
- `Owner`: 小墨
- `Created`: 2026-04-19

## Original Request

参考 https://github.com/YeLuo45/multica 集合到 Hermes，增加以下特性：

- **Agent 即队友** — Agent 有独立 Profile，在任务面板显示，参与对话，报告阻塞，主动更新状态
- **自主执行** — 完整的任务生命周期管理（入队、认领、开始、完成/失败），支持 WebSocket 实时进度流
- **可复用技能** — 每个解决方案变成可复用技能，全团队共享，技能随使用不断累积
- **统一运行时** — 统一管理所有计算环境，本地 Daemon 和云端运行时，自动检测可用 CLI，实时监控
- **多工作区** — 按团队组织工作区，工作区级别隔离，每个工作区有独立的 Agent、Issue 和设置

## Clarification

### Round 1

**Q**: 这是要将 Multica 的功能完整集成到 Hermes，还是部分功能？优先级是什么？
**A**: 核心是任务协作框架 + 技能系统。先实现基础的任务分配和自主执行，技能系统作为高优特性。

### Round 2

**Q**: 多工作区是否需要权限隔离，还是仅做数据隔离？
**A**: 先做数据隔离，权限体系作为后续迭代。

### Round 3

**Q**: 统一运行时是否需要支持远程执行（如 SSH 到其他机器）？
**A**: 第一期仅支持本地 Daemon 模式，远程执行作为后续特性。

## Final Assumptions

- 基于现有 Hermes 框架扩展，不完全重写
- 使用 JSON 文件存储工作区和任务数据（类 Multica board 的简化实现）
- Web 界面展示 Agent 任务面板
- 第一期支持本地运行，不含云端同步
- Agent Profile 存储在配置中

## Status

- `Current Status`: intake
- `PRD Confirmation`: pending
- `Technical Expectations`: pending
