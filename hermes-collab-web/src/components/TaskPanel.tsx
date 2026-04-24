import { useState, useEffect } from "react";
import { Task, Agent } from "../types";
import { agentApi } from "../api";
import { TaskCard } from "./TaskCard";
import { taskStatusConfig, priorityConfig } from "../store";
import { ChevronDown, Search, Plus, X } from "lucide-react";

interface TaskPanelProps {
  tasks: Task[];
  agents: Agent[];
  selectedTaskId: string | null;
  onSelectTask: (taskId: string) => void;
  onCreateTask: (task: {
    title: string;
    description: string;
    priority: Task["priority"];
    assignee_id: string;
  }) => void;
}

const STATUS_FILTER_OPTIONS = [
  { value: "all", label: "全部状态" },
  ...Object.entries(taskStatusConfig).map(([key, config]) => ({
    value: key,
    label: config.label,
  })),
];

const PRIORITY_FILTER_OPTIONS = [
  { value: "all", label: "全部优先级" },
  ...Object.entries(priorityConfig).map(([key, config]) => ({
    value: key,
    label: config.label,
  })),
];

export function TaskPanel({
  tasks,
  agents,
  selectedTaskId,
  onSelectTask,
  onCreateTask,
}: TaskPanelProps) {
  const [statusFilter, setStatusFilter] = useState("all");
  const [priorityFilter, setPriorityFilter] = useState("all");
  const [searchQuery, setSearchQuery] = useState("");
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [newTitle, setNewTitle] = useState("");
  const [newDescription, setNewDescription] = useState("");
  const [newPriority, setNewPriority] = useState<Task["priority"]>("medium");
  const [newOwner, setNewOwner] = useState("");

  // Fetch agents from API
  const [agentList, setAgentList] = useState<Agent[]>(agents);

  useEffect(() => {
    const fetchAgents = async () => {
      const res = await agentApi.list();
      if (res.success && res.data) {
        setAgentList(res.data);
      }
    };
    fetchAgents();
  }, []);

  // Filter tasks
  const filteredTasks = tasks.filter((task) => {
    if (statusFilter !== "all" && task.status !== statusFilter) return false;
    if (priorityFilter !== "all" && task.priority !== priorityFilter)
      return false;
    if (searchQuery) {
      const query = searchQuery.toLowerCase();
      return (
        task.title.toLowerCase().includes(query) ||
        task.description.toLowerCase().includes(query) ||
        task.proposalId?.toLowerCase().includes(query)
      );
    }
    return true;
  });

  // Sort by updated time
  const sortedTasks = [...filteredTasks].sort(
    (a, b) => b.updatedAt - a.updatedAt
  );

  const handleCreate = () => {
    if (newTitle.trim() && newOwner) {
      onCreateTask({
        title: newTitle.trim(),
        description: newDescription.trim(),
        priority: newPriority,
        assignee_id: newOwner,
      });
      setNewTitle("");
      setNewDescription("");
      setNewPriority("medium");
      setNewOwner("");
      setShowCreateModal(false);
    }
  };

  return (
    <div className="h-full flex flex-col">
      {/* Header */}
      <div className="px-4 py-3 border-b border-dark-100 flex items-center justify-between">
        <div>
          <h2 className="text-lg font-medium text-white">任务列表</h2>
          <div className="text-sm text-gray-500 mt-0.5">
            {filteredTasks.length} 个任务
          </div>
        </div>
        <button
          onClick={() => setShowCreateModal(true)}
          className="flex items-center gap-1.5 px-3 py-1.5 bg-primary-500 hover:bg-primary-600 text-white rounded-lg transition-colors"
        >
          <Plus className="w-4 h-4" />
          <span>创建任务</span>
        </button>
      </div>

      {/* Filters */}
      <div className="px-4 py-2 border-b border-dark-100 space-y-2">
        {/* Search */}
        <div className="relative">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-500" />
          <input
            type="text"
            placeholder="搜索任务..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full pl-9 pr-3 py-2 bg-dark-200 border border-dark-100 rounded-lg text-white placeholder-gray-500 focus:outline-none focus:border-primary-500"
          />
        </div>

        {/* Filter Dropdowns */}
        <div className="flex gap-2">
          {/* Status Filter */}
          <div className="relative flex-1">
            <select
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
              className="w-full appearance-none px-3 py-1.5 bg-dark-200 border border-dark-100 rounded-lg text-white text-sm focus:outline-none focus:border-primary-500 cursor-pointer"
            >
              {STATUS_FILTER_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
            <ChevronDown className="absolute right-2 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-500 pointer-events-none" />
          </div>

          {/* Priority Filter */}
          <div className="relative flex-1">
            <select
              value={priorityFilter}
              onChange={(e) => setPriorityFilter(e.target.value)}
              className="w-full appearance-none px-3 py-1.5 bg-dark-200 border border-dark-100 rounded-lg text-white text-sm focus:outline-none focus:border-primary-500 cursor-pointer"
            >
              {PRIORITY_FILTER_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
            <ChevronDown className="absolute right-2 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-500 pointer-events-none" />
          </div>
        </div>
      </div>

      {/* Task List */}
      <div className="flex-1 overflow-y-auto p-3 space-y-3">
        {sortedTasks.length === 0 ? (
          <div className="text-center text-gray-500 py-8">暂无任务</div>
        ) : (
          sortedTasks.map((task) => (
            <TaskCard
              key={task.id}
              task={task}
              isSelected={selectedTaskId === task.id}
              onClick={() => onSelectTask(task.id)}
            />
          ))
        )}
      </div>

      {/* Create Task Modal */}
      {showCreateModal && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-dark-200 rounded-xl w-[480px] border border-dark-100">
            <div className="px-4 py-3 border-b border-dark-100 flex items-center justify-between">
              <h3 className="text-lg font-medium text-white">创建任务</h3>
              <button
                onClick={() => setShowCreateModal(false)}
                className="p-1 hover:bg-dark-100 rounded transition-colors"
              >
                <X className="w-5 h-5 text-gray-400" />
              </button>
            </div>

            <div className="p-4 space-y-4">
              {/* Title */}
              <div>
                <label className="block text-sm text-gray-400 mb-1">
                  任务标题 *
                </label>
                <input
                  type="text"
                  value={newTitle}
                  onChange={(e) => setNewTitle(e.target.value)}
                  placeholder="输入任务标题"
                  className="w-full px-3 py-2 bg-dark-100 border border-dark-100 rounded-lg text-white placeholder-gray-500 focus:outline-none focus:border-primary-500"
                />
              </div>

              {/* Description */}
              <div>
                <label className="block text-sm text-gray-400 mb-1">
                  任务描述
                </label>
                <textarea
                  value={newDescription}
                  onChange={(e) => setNewDescription(e.target.value)}
                  placeholder="输入任务描述"
                  rows={3}
                  className="w-full px-3 py-2 bg-dark-100 border border-dark-100 rounded-lg text-white placeholder-gray-500 focus:outline-none focus:border-primary-500 resize-none"
                />
              </div>

              {/* Priority & Agent */}
              <div className="flex gap-4">
                {/* Priority */}
                <div className="flex-1">
                  <label className="block text-sm text-gray-400 mb-1">
                    优先级
                  </label>
                  <div className="relative">
                    <select
                      value={newPriority}
                      onChange={(e) =>
                        setNewPriority(e.target.value as Task["priority"])
                      }
                      className="w-full appearance-none px-3 py-2 bg-dark-100 border border-dark-100 rounded-lg text-white focus:outline-none focus:border-primary-500 cursor-pointer"
                    >
                      <option value="low">低</option>
                      <option value="medium">中</option>
                      <option value="high">高</option>
                      <option value="urgent">紧急</option>
                    </select>
                    <ChevronDown className="absolute right-2 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-500 pointer-events-none" />
                  </div>
                </div>

                {/* Agent Selection */}
                <div className="flex-1">
                  <label className="block text-sm text-gray-400 mb-1">
                    负责人 Agent *
                  </label>
                  <div className="relative">
                    <select
                      value={newOwner}
                      onChange={(e) => setNewOwner(e.target.value)}
                      className="w-full appearance-none px-3 py-2 bg-dark-100 border border-dark-100 rounded-lg text-white focus:outline-none focus:border-primary-500 cursor-pointer"
                    >
                      <option value="">选择 Agent</option>
                      {agentList.map((agent) => (
                        <option key={agent.id} value={agent.id}>
                          {agent.name} ({agent.role === "main" ? "主控" : agent.role === "pm" ? "产品" : "开发"})
                        </option>
                      ))}
                    </select>
                    <ChevronDown className="absolute right-2 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-500 pointer-events-none" />
                  </div>
                </div>
              </div>

              {/* Actions */}
              <div className="flex justify-end gap-2 pt-2">
                <button
                  onClick={() => setShowCreateModal(false)}
                  className="px-4 py-2 text-gray-400 hover:text-white transition-colors"
                >
                  取消
                </button>
                <button
                  onClick={handleCreate}
                  disabled={!newTitle.trim() || !newOwner}
                  className="px-4 py-2 bg-primary-500 text-white rounded-lg hover:bg-primary-600 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  创建
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
