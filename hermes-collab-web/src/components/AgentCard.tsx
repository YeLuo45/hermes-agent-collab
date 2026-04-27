import { Agent } from "../types";
import { statusConfig, formatRelativeTime } from "../store";

interface AgentCardProps {
  agent: Agent;
  isSelected: boolean;
  onClick: () => void;
}

export function AgentCard({ agent, isSelected, onClick }: AgentCardProps) {
  const config = statusConfig[agent.status] || statusConfig.idle;

  return (
    <div
      onClick={onClick}
      className={`p-4 rounded-lg cursor-pointer transition-all duration-200 ${
        isSelected
          ? "bg-primary-500/20 border-2 border-primary-500"
          : "bg-dark-200 border-2 border-transparent hover:border-primary-500/30"
      }`}
    >
      <div className="flex items-start gap-3">
        {/* Avatar */}
        <div className="text-3xl">{agent.avatar || "🤖"}</div>

        <div className="flex-1 min-w-0">
          {/* Name */}
          <div className="flex items-center gap-2">
            <span className="font-medium text-white">{agent.name}</span>
            <span
              className={`w-2 h-2 rounded-full ${config.bgColor} ${
                agent.status === "working" ? "animate-pulse" : ""
              }`}
            />
          </div>

          {/* Role */}
          <div className="text-xs text-gray-500 mt-0.5">
            {agent.role === "main"
              ? "主控 Agent"
              : agent.role === "pm"
              ? "产品经理"
              : "开发者"}
          </div>

          {/* Status */}
          <div className={`text-sm ${config.color} mt-1`}>
            {config.label}
          </div>

          {/* Current Task */}
          {agent.currentTask && (
            <div className="mt-2 text-sm text-gray-400 truncate">
              {agent.currentTask}
            </div>
          )}

          {/* Last Active */}
          <div className="text-xs text-gray-600 mt-2">
            {formatRelativeTime(agent.lastActive)}
          </div>
        </div>
      </div>
    </div>
  );
}
