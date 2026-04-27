import { Task } from "../types";
import {
  taskStatusConfig,
  priorityConfig,
  formatRelativeTime,
} from "../store";

interface TaskCardProps {
  task: Task;
  isSelected: boolean;
  onClick: () => void;
}

export function TaskCard({ task, isSelected, onClick }: TaskCardProps) {
  const status = taskStatusConfig[task.status] || taskStatusConfig.pending;
  const priority = priorityConfig[task.priority] || priorityConfig.medium;

  return (
    <div
      onClick={onClick}
      className={`p-4 rounded-lg cursor-pointer transition-all duration-200 ${
        isSelected
          ? "bg-primary-500/20 border-2 border-primary-500"
          : "bg-dark-200 border-2 border-transparent hover:border-primary-500/30"
      }`}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="flex-1 min-w-0">
          {/* Title */}
          <div className="font-medium text-white truncate">{task.title}</div>

          {/* Proposal ID */}
          {task.proposalId && (
            <div className="text-xs text-primary-400 mt-0.5">
              {task.proposalId}
            </div>
          )}

          {/* Description */}
          <div className="text-sm text-gray-400 mt-1 line-clamp-2">
            {task.description}
          </div>

          {/* Tags */}
          {task.tags && task.tags.length > 0 && (
            <div className="flex flex-wrap gap-1 mt-2">
              {task.tags.map((tag) => (
                <span
                  key={tag}
                  className="px-2 py-0.5 text-xs bg-dark-100 text-gray-400 rounded"
                >
                  {tag}
                </span>
              ))}
            </div>
          )}

          {/* Footer */}
          <div className="flex items-center gap-3 mt-3">
            {/* Status Badge */}
            <span
              className={`px-2 py-0.5 text-xs rounded ${status.bgColor}/20 ${status.color}`}
            >
              {status.label}
            </span>

            {/* Priority */}
            <span className={`text-xs ${priority.color}`}>
              {priority.label}优先级
            </span>
          </div>
        </div>

        {/* Time */}
        <div className="text-xs text-gray-600 whitespace-nowrap">
          {formatRelativeTime(task.updatedAt)}
        </div>
      </div>
    </div>
  );
}
