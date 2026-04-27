import { Agent, Task } from "../types";

interface StatusBarProps {
  agents: Agent[];
  tasks: Task[];
  wsConnected: boolean;
  onOpenChat?: () => void;
}

export function StatusBar({ agents, tasks, wsConnected, onOpenChat }: StatusBarProps) {
  const activeAgents = agents.filter(
    (a) => a.status === "working" || a.status === "thinking"
  );
  const activeTasks = tasks.filter(
    (t) => t.status === "in_progress" || t.status === "in_dev" || t.status === "in_acceptance"
  );

  return (
    <footer className="bg-dark-300 border-t border-dark-100 px-6 py-2">
      <div className="flex items-center justify-between text-sm">
        {/* Left: Stats */}
        <div className="flex items-center gap-6">
          <div className="flex items-center gap-2">
            <div className="w-2 h-2 rounded-full bg-green-500" />
            <span className="text-gray-400">
              在线 Agent: {agents.filter((a) => a.status !== "offline").length}
            </span>
          </div>
          <div className="text-gray-500">
            活跃:{" "}
            <span className="text-white">{activeAgents.length}</span>
          </div>
          <div className="text-gray-500">
            进行中任务:{" "}
            <span className="text-white">{activeTasks.length}</span>
          </div>
        </div>

        {/* Right: Connection Status */}
        <div className="flex items-center gap-4">
          <button
            onClick={onOpenChat}
            className="flex items-center gap-2 px-3 py-1 bg-primary-500/20 hover:bg-primary-500/30 text-primary-400 rounded transition-colors"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
            </svg>
            <span className="text-sm">与 Agent 对话</span>
          </button>
          <div className="flex items-center gap-2">
            <div
              className={`w-2 h-2 rounded-full ${
                wsConnected ? "bg-green-500" : "bg-red-500"
              }`}
            />
            <span className="text-gray-500">
              {wsConnected ? "WebSocket 已连接" : "WebSocket 未连接"}
            </span>
          </div>
        </div>
      </div>
    </footer>
  );
}
