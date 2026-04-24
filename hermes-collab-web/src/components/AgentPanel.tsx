import { useState } from "react";
import { Agent } from "../types";
import { AgentCard } from "./AgentCard";
import { Plus, X, Loader2, AlertCircle } from "lucide-react";
import { agentApi } from "../api";

interface AgentPanelProps {
  agents: Agent[];
  selectedAgentId: string | null;
  onSelectAgent: (agentId: string) => void;
  currentWorkspaceId?: string | null;
  onAgentCreated?: (agent: Agent) => void;
}

export function AgentPanel({
  agents,
  selectedAgentId,
  onSelectAgent,
  currentWorkspaceId,
  onAgentCreated,
}: AgentPanelProps) {
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [createLoading, setCreateLoading] = useState(false);
  const [newAgentName, setNewAgentName] = useState("");
  const [newAgentRole, setNewAgentRole] = useState<Agent["role"]>("dev");
  const [error, setError] = useState<string | null>(null);

  const handleCreateAgent = async () => {
    // Check workspace selection
    if (!currentWorkspaceId) {
      setError("请先选择工作区");
      return;
    }

    if (!newAgentName.trim()) {
      setError("请输入 Agent 名称");
      return;
    }

    setCreateLoading(true);
    setError(null);
    try {
      const result = await agentApi.register({
        name: newAgentName.trim(),
        role: newAgentRole,
        workspaceId: currentWorkspaceId,
      });
      if (result.success && result.data) {
        // Transform API response to full Agent type
        const newAgent: Agent = {
          ...result.data,
          status: "idle",
          lastActive: Date.now(),
        };
        onAgentCreated?.(newAgent);
        setShowCreateModal(false);
        setNewAgentName("");
        setNewAgentRole("dev");
      } else {
        setError(result.error || "创建失败");
      }
    } catch {
      setError("网络错误");
    } finally {
      setCreateLoading(false);
    }
  };

  const handleCloseModal = () => {
    setShowCreateModal(false);
    setNewAgentName("");
    setNewAgentRole("dev");
    setError(null);
  };

  return (
    <div className="h-full flex flex-col">
      {/* Header */}
      <div className="px-4 py-3 border-b border-dark-100 flex items-center justify-between">
        <div>
          <h2 className="text-lg font-medium text-white">Agent 状态</h2>
          <div className="text-sm text-gray-500 mt-0.5">
            在线: {agents.filter((a) => a.status !== "offline").length} /{" "}
            {agents.length}
          </div>
        </div>
        <button
          onClick={() => setShowCreateModal(true)}
          className="flex items-center gap-1.5 px-3 py-1.5 bg-primary-500 hover:bg-primary-600 text-white rounded-lg transition-colors"
        >
          <Plus className="w-4 h-4" />
          <span>创建 Agent</span>
        </button>
      </div>

      {/* Agent List */}
      <div className="flex-1 overflow-y-auto p-3 space-y-3">
        {agents.map((agent) => (
          <AgentCard
            key={agent.id}
            agent={agent}
            isSelected={selectedAgentId === agent.id}
            onClick={() => onSelectAgent(agent.id)}
          />
        ))}
      </div>

      {/* Create Agent Modal */}
      {showCreateModal && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-dark-200 rounded-xl w-[400px] border border-dark-100">
            <div className="px-4 py-3 border-b border-dark-100 flex items-center justify-between">
              <h3 className="text-lg font-medium text-white">创建 Agent</h3>
              <button
                onClick={handleCloseModal}
                className="p-1 hover:bg-dark-100 rounded transition-colors"
              >
                <X className="w-5 h-5 text-gray-400" />
              </button>
            </div>

            <div className="p-4 space-y-4">
              {/* Error Message */}
              {error && (
                <div className="flex items-center gap-2 px-3 py-2 bg-red-500/20 border border-red-500/30 rounded-lg text-red-400 text-sm">
                  <AlertCircle className="w-4 h-4 flex-shrink-0" />
                  <span>{error}</span>
                </div>
              )}

              {/* Workspace Warning */}
              {!currentWorkspaceId && (
                <div className="flex items-center gap-2 px-3 py-2 bg-yellow-500/20 border border-yellow-500/30 rounded-lg text-yellow-400 text-sm">
                  <AlertCircle className="w-4 h-4 flex-shrink-0" />
                  <span>请先在顶部选择工作区</span>
                </div>
              )}

              {/* Agent Name */}
              <div>
                <label className="block text-sm text-gray-400 mb-1">
                  Agent 名称 *
                </label>
                <input
                  type="text"
                  value={newAgentName}
                  onChange={(e) => setNewAgentName(e.target.value)}
                  placeholder="输入 Agent 名称"
                  disabled={!currentWorkspaceId}
                  className="w-full px-3 py-2 bg-dark-100 border border-dark-100 rounded-lg text-white placeholder-gray-500 focus:outline-none focus:border-primary-500 disabled:opacity-50 disabled:cursor-not-allowed"
                />
              </div>

              {/* Agent Role */}
              <div>
                <label className="block text-sm text-gray-400 mb-1">角色</label>
                <select
                  value={newAgentRole}
                  onChange={(e) => setNewAgentRole(e.target.value as Agent["role"])}
                  disabled={!currentWorkspaceId}
                  className="w-full px-3 py-2 bg-dark-100 border border-dark-100 rounded-lg text-white focus:outline-none focus:border-primary-500 disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer"
                >
                  <option value="main">主控 Agent</option>
                  <option value="pm">产品经理</option>
                  <option value="dev">开发者</option>
                </select>
              </div>

              {/* Actions */}
              <div className="flex justify-end gap-2 pt-2">
                <button
                  onClick={handleCloseModal}
                  className="px-4 py-2 text-gray-400 hover:text-white transition-colors"
                >
                  取消
                </button>
                <button
                  onClick={handleCreateAgent}
                  disabled={!currentWorkspaceId || createLoading}
                  className="flex items-center gap-2 px-4 py-2 bg-primary-500 text-white rounded-lg hover:bg-primary-600 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {createLoading && <Loader2 className="w-4 h-4 animate-spin" />}
                  <span>创建</span>
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
