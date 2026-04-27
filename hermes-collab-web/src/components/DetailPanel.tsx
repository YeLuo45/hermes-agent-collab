import { useState } from "react";
import { Agent, Task } from "../types";
import { statusConfig, taskStatusConfig, priorityConfig, formatRelativeTime } from "../store";
import { X, User, Clock, Tag, FileText, AlertCircle, Send, MessageCircle } from "lucide-react";

interface Message {
  id: string;
  role: "user" | "agent";
  content: string;
  timestamp: number;
}

interface DetailPanelProps {
  agent: Agent | null;
  task: Task | null;
  onClose: () => void;
}

export function DetailPanel({ agent, task, onClose }: DetailPanelProps) {
  // Show agent detail with chat
  if (agent) {
    const status = statusConfig[agent.status] || statusConfig.idle;
    const [messages, setMessages] = useState<Message[]>([
      {
        id: "1",
        role: "agent",
        content: `你好！我是 ${agent.name}。有什么我可以帮你的吗？`,
        timestamp: Date.now() - 60000,
      },
    ]);
    const [inputValue, setInputValue] = useState("");
    const [showChat, setShowChat] = useState(false);

    const handleSend = () => {
      if (!inputValue.trim()) return;

      const userMsg: Message = {
        id: Date.now().toString(),
        role: "user",
        content: inputValue.trim(),
        timestamp: Date.now(),
      };
      setMessages((prev) => [...prev, userMsg]);
      setInputValue("");

      // Simulate agent response
      setTimeout(() => {
        const agentMsg: Message = {
          id: (Date.now() + 1).toString(),
          role: "agent",
          content: `收到你的消息：${userMsg.content}\n\n我现在 ${status.label} 中，${agent.currentTask ? `正在处理：${agent.currentTask}` : "当前没有进行中的任务"}。`,
          timestamp: Date.now(),
        };
        setMessages((prev) => [...prev, agentMsg]);
      }, 800);
    };

    const handleKeyDown = (e: React.KeyboardEvent) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        handleSend();
      }
    };

    return (
      <div className="h-full flex flex-col bg-dark-200">
        {/* Header */}
        <div className="px-4 py-3 border-b border-dark-100 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="text-3xl">{agent.avatar || "🤖"}</div>
            <div>
              <div className="font-medium text-white">{agent.name}</div>
              <div className="text-sm text-gray-500">
                {agent.role === "main"
                  ? "主控 Agent"
                  : agent.role === "pm"
                  ? "产品经理"
                  : "开发者"}
              </div>
            </div>
          </div>
          <div className="flex items-center gap-1">
            <button
              onClick={() => setShowChat(!showChat)}
              className={`p-2 hover:bg-dark-100 rounded-lg transition-colors ${
                showChat ? "text-primary-400" : "text-gray-400"
              }`}
              title="聊天"
            >
              <MessageCircle className="w-5 h-5" />
            </button>
            <button
              onClick={onClose}
              className="p-2 hover:bg-dark-100 rounded-lg transition-colors"
            >
              <X className="w-5 h-5 text-gray-400" />
            </button>
          </div>
        </div>

        {/* Chat View */}
        {showChat ? (
          <div className="flex-1 flex flex-col overflow-hidden">
            {/* Messages */}
            <div className="flex-1 overflow-y-auto p-4 space-y-4">
              {messages.map((msg) => (
                <div
                  key={msg.id}
                  className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}
                >
                  <div
                    className={`max-w-[80%] px-4 py-2 rounded-2xl ${
                      msg.role === "user"
                        ? "bg-primary-500 text-white rounded-br-md"
                        : "bg-dark-100 text-gray-200 rounded-bl-md"
                    }`}
                  >
                    <div className="text-sm whitespace-pre-wrap">{msg.content}</div>
                    <div
                      className={`text-xs mt-1 ${
                        msg.role === "user" ? "text-primary-200" : "text-gray-500"
                      }`}
                    >
                      {formatRelativeTime(msg.timestamp)}
                    </div>
                  </div>
                </div>
              ))}
            </div>

            {/* Input */}
            <div className="p-4 border-t border-dark-100">
              <div className="flex gap-2">
                <input
                  type="text"
                  value={inputValue}
                  onChange={(e) => setInputValue(e.target.value)}
                  onKeyDown={handleKeyDown}
                  placeholder={`向 ${agent.name} 发送消息...`}
                  className="flex-1 px-4 py-2 bg-dark-100 border border-dark-100 rounded-full text-white placeholder-gray-500 focus:outline-none focus:border-primary-500"
                />
                <button
                  onClick={handleSend}
                  disabled={!inputValue.trim()}
                  className="p-2 bg-primary-500 hover:bg-primary-600 text-white rounded-full disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                >
                  <Send className="w-5 h-5" />
                </button>
              </div>
            </div>
          </div>
        ) : (
          /* Info View */
          <div className="flex-1 overflow-y-auto p-4 space-y-4">
            {/* Status */}
            <div className="flex items-center gap-3">
              <div
                className={`w-3 h-3 rounded-full ${status.bgColor} ${
                  agent.status === "working" ? "animate-pulse" : ""
                }`}
              />
              <span className={status.color}>{status.label}</span>
            </div>

            {/* Current Task */}
            {agent.currentTask && (
              <div className="p-3 bg-dark-100 rounded-lg">
                <div className="text-sm text-gray-500 mb-1">当前任务</div>
                <div className="text-white">{agent.currentTask}</div>
              </div>
            )}

            {/* Last Active */}
            <div className="flex items-center gap-2 text-sm text-gray-400">
              <Clock className="w-4 h-4" />
              <span>最后活跃: {formatRelativeTime(agent.lastActive)}</span>
            </div>

            {/* Skills Preview */}
            <div className="p-3 bg-dark-100 rounded-lg">
              <div className="text-sm text-gray-500 mb-2">可用技能</div>
              <div className="flex flex-wrap gap-2">
                <span className="px-2 py-1 text-xs bg-primary-500/20 text-primary-400 rounded">
                  代码审查
                </span>
                <span className="px-2 py-1 text-xs bg-blue-500/20 text-blue-400 rounded">
                  PRD 撰写
                </span>
                <span className="px-2 py-1 text-xs bg-green-500/20 text-green-400 rounded">
                  API 文档
                </span>
              </div>
            </div>
          </div>
        )}
      </div>
    );
  }

  // Show task detail
  if (task) {
    const status = taskStatusConfig[task.status] || taskStatusConfig.pending;
    const priority = priorityConfig[task.priority] || priorityConfig.medium;

    return (
      <div className="h-full flex flex-col bg-dark-200">
        {/* Header */}
        <div className="px-4 py-3 border-b border-dark-100 flex items-center justify-between">
          <div className="flex-1 min-w-0">
            <div className="font-medium text-white truncate">{task.title}</div>
            {task.proposalId && (
              <div className="text-sm text-primary-400">{task.proposalId}</div>
            )}
          </div>
          <button
            onClick={onClose}
            className="p-2 hover:bg-dark-100 rounded-lg transition-colors"
          >
            <X className="w-5 h-5 text-gray-400" />
          </button>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-4 space-y-4">
          {/* Status & Priority */}
          <div className="flex items-center gap-3">
            <span
              className={`px-3 py-1 rounded-lg text-sm ${status.bgColor}/20 ${status.color}`}
            >
              {status.label}
            </span>
            <span className={`text-sm ${priority.color}`}>
              {priority.label}优先级
            </span>
          </div>

          {/* Description */}
          <div className="p-4 bg-dark-100 rounded-lg">
            <div className="flex items-center gap-2 text-gray-500 mb-2">
              <FileText className="w-4 h-4" />
              <span>描述</span>
            </div>
            <div className="text-white">{task.description}</div>
          </div>

          {/* Tags */}
          {task.tags && task.tags.length > 0 && (
            <div className="flex items-start gap-2">
              <Tag className="w-4 h-4 text-gray-500 mt-0.5" />
              <div className="flex flex-wrap gap-2">
                {task.tags.map((tag) => (
                  <span
                    key={tag}
                    className="px-2 py-1 text-sm bg-dark-100 text-gray-400 rounded"
                  >
                    {tag}
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* Time Info */}
          <div className="space-y-2">
            <div className="flex items-center gap-2 text-sm text-gray-400">
              <Clock className="w-4 h-4" />
              <span>创建: {new Date(task.createdAt).toLocaleString("zh-CN")}</span>
            </div>
            <div className="flex items-center gap-2 text-sm text-gray-400">
              <Clock className="w-4 h-4" />
              <span>更新: {new Date(task.updatedAt).toLocaleString("zh-CN")}</span>
            </div>
          </div>

          {/* Owner */}
          <div className="flex items-center gap-2 text-sm text-gray-400">
            <User className="w-4 h-4" />
            <span>负责人: {task.owner}</span>
          </div>
        </div>
      </div>
    );
  }

  // Empty state
  return (
    <div className="h-full flex items-center justify-center bg-dark-200">
      <div className="text-center text-gray-500">
        <AlertCircle className="w-12 h-12 mx-auto mb-2 opacity-50" />
        <p>选择一个 Agent 或任务查看详情</p>
      </div>
    </div>
  );
}
