import { useState } from "react";
import { Folder, Plus, Settings, X, Check, Pencil, Trash2 } from "lucide-react";
import { workspaceApi } from "../api";

export interface Workspace {
  id: string;
  name: string;
  description?: string;
  agentCount: number;
  taskCount: number;
  createdAt: number;
}

interface WorkspaceSelectorProps {
  currentWorkspace: Workspace | null;
  workspaces: Workspace[];
  onSelect: (ws: Workspace) => void;
  onCreate: (name: string, description?: string) => void;
  onUpdate: (id: string, name: string, description?: string) => void;
  onDelete: (id: string) => void;
}

// Demo workspaces
export const demoWorkspaces: Workspace[] = [
  {
    id: "ws-1",
    name: "默认工作区",
    description: "项目主工作区",
    agentCount: 3,
    taskCount: 5,
    createdAt: Date.now() - 86400000 * 7,
  },
  {
    id: "ws-2",
    name: "开发项目",
    description: "开发团队专用",
    agentCount: 5,
    taskCount: 12,
    createdAt: Date.now() - 86400000 * 3,
  },
];

export function WorkspaceSelector({
  currentWorkspace,
  workspaces,
  onSelect,
  onCreate,
  onUpdate,
  onDelete,
}: WorkspaceSelectorProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [showManage, setShowManage] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editName, setEditName] = useState("");
  const [editDesc, setEditDesc] = useState("");
  const [showCreate, setShowCreate] = useState(false);
  const [newName, setNewName] = useState("");
  const [newDesc, setNewDesc] = useState("");

  const handleStartEdit = (ws: Workspace) => {
    setEditingId(ws.id);
    setEditName(ws.name);
    setEditDesc(ws.description || "");
  };

  const handleSaveEdit = async () => {
    if (editingId) {
      await workspaceApi.update(editingId, { name: editName, description: editDesc });
      onUpdate(editingId, editName, editDesc);
      setEditingId(null);
    }
  };

  const handleDelete = async (id: string) => {
    if (confirm('确定要删除此工作区吗？')) {
      await workspaceApi.delete(id);
      onDelete(id);
    }
  };

  const handleCreate = () => {
    if (newName.trim()) {
      onCreate(newName.trim(), newDesc.trim() || undefined);
      setNewName("");
      setNewDesc("");
      setShowCreate(false);
    }
  };

  return (
    <>
      {/* Selector Button */}
      <div className="relative">
        <button
          onClick={() => setIsOpen(!isOpen)}
          className="flex items-center gap-2 px-3 py-1.5 bg-dark-200 hover:bg-dark-100 rounded-lg transition-colors"
        >
          <Folder className="w-4 h-4 text-primary-400" />
          <span className="text-white text-sm">
            {currentWorkspace?.name || "选择工作区"}
          </span>
        </button>

        {/* Dropdown */}
        {isOpen && (
          <div className="absolute top-full left-0 mt-1 w-64 bg-dark-200 border border-dark-100 rounded-lg shadow-xl z-50">
            <div className="p-2 border-b border-dark-100">
              <button
                onClick={() => {
                  setShowManage(true);
                  setIsOpen(false);
                }}
                className="w-full flex items-center gap-2 px-2 py-1.5 text-sm text-gray-400 hover:text-white hover:bg-dark-100 rounded transition-colors"
              >
                <Settings className="w-4 h-4" />
                <span>管理工作区</span>
              </button>
            </div>
            <div className="p-2 max-h-64 overflow-y-auto">
              {workspaces.map((ws) => (
                <button
                  key={ws.id}
                  onClick={() => {
                    onSelect(ws);
                    setIsOpen(false);
                  }}
                  className={`w-full flex items-center gap-2 px-2 py-2 rounded transition-colors ${
                    currentWorkspace?.id === ws.id
                      ? "bg-primary-500/20 text-primary-400"
                      : "text-gray-300 hover:bg-dark-100"
                  }`}
                >
                  <Folder className="w-4 h-4" />
                  <div className="flex-1 text-left">
                    <div className="text-sm">{ws.name}</div>
                    <div className="text-xs text-gray-500">
                      {ws.agentCount} agents · {ws.taskCount} tasks
                    </div>
                  </div>
                </button>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Management Modal */}
      {showManage && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-dark-200 rounded-xl w-[500px] max-h-[80vh] overflow-hidden border border-dark-100">
            <div className="px-4 py-3 border-b border-dark-100 flex items-center justify-between">
              <h3 className="text-lg font-medium text-white">管理工作区</h3>
              <button
                onClick={() => setShowManage(false)}
                className="p-1 hover:bg-dark-100 rounded transition-colors"
              >
                <X className="w-5 h-5 text-gray-400" />
              </button>
            </div>

            <div className="p-4">
              {/* Create new workspace */}
              {showCreate ? (
                <div className="mb-4 p-3 bg-dark-100 rounded-lg">
                  <input
                    type="text"
                    placeholder="工作区名称"
                    value={newName}
                    onChange={(e) => setNewName(e.target.value)}
                    className="w-full px-3 py-2 bg-dark-300 border border-dark-100 rounded-lg text-white placeholder-gray-500 focus:outline-none focus:border-primary-500 mb-2"
                  />
                  <input
                    type="text"
                    placeholder="描述（可选）"
                    value={newDesc}
                    onChange={(e) => setNewDesc(e.target.value)}
                    className="w-full px-3 py-2 bg-dark-300 border border-dark-100 rounded-lg text-white placeholder-gray-500 focus:outline-none focus:border-primary-500 mb-3"
                  />
                  <div className="flex gap-2">
                    <button
                      onClick={handleCreate}
                      className="flex items-center gap-1 px-3 py-1.5 bg-primary-500 text-white rounded-lg hover:bg-primary-600 transition-colors"
                    >
                      <Check className="w-4 h-4" />
                      <span>创建</span>
                    </button>
                    <button
                      onClick={() => {
                        setShowCreate(false);
                        setNewName("");
                        setNewDesc("");
                      }}
                      className="px-3 py-1.5 text-gray-400 hover:text-white transition-colors"
                    >
                      取消
                    </button>
                  </div>
                </div>
              ) : (
                <button
                  onClick={() => setShowCreate(true)}
                  className="w-full flex items-center justify-center gap-2 px-3 py-2 mb-4 border border-dashed border-dark-100 rounded-lg text-gray-400 hover:text-white hover:border-primary-500 transition-colors"
                >
                  <Plus className="w-4 h-4" />
                  <span>创建新工作区</span>
                </button>
              )}

              {/* Workspace List */}
              <div className="space-y-2">
                {workspaces.map((ws) => (
                  <div
                    key={ws.id}
                    className="p-3 bg-dark-100 rounded-lg flex items-center gap-3"
                  >
                    {editingId === ws.id ? (
                      <div className="flex-1">
                        <input
                          type="text"
                          value={editName}
                          onChange={(e) => setEditName(e.target.value)}
                          className="w-full px-2 py-1 bg-dark-300 border border-dark-100 rounded text-white focus:outline-none focus:border-primary-500 mb-1"
                        />
                        <input
                          type="text"
                          value={editDesc}
                          onChange={(e) => setEditDesc(e.target.value)}
                          className="w-full px-2 py-1 bg-dark-300 border border-dark-100 rounded text-white text-sm focus:outline-none focus:border-primary-500"
                        />
                        <div className="flex gap-2 mt-2">
                          <button
                            onClick={handleSaveEdit}
                            className="text-xs text-primary-400 hover:text-primary-300"
                          >
                            保存
                          </button>
                          <button
                            onClick={() => setEditingId(null)}
                            className="text-xs text-gray-400 hover:text-white"
                          >
                            取消
                          </button>
                        </div>
                      </div>
                    ) : (
                      <>
                        <Folder className="w-5 h-5 text-primary-400" />
                        <div className="flex-1">
                          <div className="text-white">{ws.name}</div>
                          {ws.description && (
                            <div className="text-xs text-gray-500">
                              {ws.description}
                            </div>
                          )}
                          <div className="text-xs text-gray-600 mt-0.5">
                            {ws.agentCount} agents · {ws.taskCount} tasks
                          </div>
                        </div>
                        <div className="flex gap-1">
                          <button
                            onClick={() => handleStartEdit(ws)}
                            className="p-1.5 text-gray-500 hover:text-white hover:bg-dark-300 rounded transition-colors"
                          >
                            <Pencil className="w-4 h-4" />
                          </button>
                          {ws.id !== "ws-1" && (
                            <button
                              onClick={() => handleDelete(ws.id)}
                              className="p-1.5 text-gray-500 hover:text-red-400 hover:bg-dark-300 rounded transition-colors"
                            >
                              <Trash2 className="w-4 h-4" />
                            </button>
                          )}
                        </div>
                      </>
                    )}
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
