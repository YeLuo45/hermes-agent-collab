import { useState } from "react";
import { Wifi, WifiOff, RefreshCw } from "lucide-react";
import {
  WorkspaceSelector,
  Workspace,
  demoWorkspaces,
} from "./WorkspaceSelector";

interface HeaderProps {
  wsConnected: boolean;
  onReconnect?: () => void;
  workspaces?: Workspace[];
  currentWorkspace?: Workspace | null;
  onWorkspaceChange?: (ws: Workspace) => void;
  onWorkspaceCreate?: (name: string, desc?: string) => void;
  onWorkspaceUpdate?: (id: string, name: string, desc?: string) => void;
  onWorkspaceDelete?: (id: string) => void;
}

export function Header({
  wsConnected,
  onReconnect,
  workspaces = demoWorkspaces,
  currentWorkspace = demoWorkspaces[0],
  onWorkspaceChange,
  onWorkspaceCreate,
  onWorkspaceUpdate,
  onWorkspaceDelete,
}: HeaderProps) {
  const [localWorkspaces, setLocalWorkspaces] = useState<Workspace[]>(workspaces);
  const [selectedWs, setSelectedWs] = useState<Workspace | null>(
    currentWorkspace
  );

  const handleSelectWorkspace = (ws: Workspace) => {
    setSelectedWs(ws);
    onWorkspaceChange?.(ws);
  };

  const handleCreateWorkspace = (name: string, description?: string) => {
    const newWs: Workspace = {
      id: `ws-${Date.now()}`,
      name,
      description,
      agentCount: 0,
      taskCount: 0,
      createdAt: Date.now(),
    };
    setLocalWorkspaces((prev) => [...prev, newWs]);
    onWorkspaceCreate?.(name, description);
  };

  const handleUpdateWorkspace = (id: string, name: string, description?: string) => {
    setLocalWorkspaces((prev) =>
      prev.map((ws) => (ws.id === id ? { ...ws, name, description } : ws))
    );
    onWorkspaceUpdate?.(id, name, description);
  };

  const handleDeleteWorkspace = (id: string) => {
    setLocalWorkspaces((prev) => prev.filter((ws) => ws.id !== id));
    if (selectedWs?.id === id) {
      setSelectedWs(localWorkspaces[0]);
    }
    onWorkspaceDelete?.(id);
  };

  return (
    <header className="bg-dark-300 border-b border-dark-100 px-6 py-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-6">
          <div className="text-2xl font-bold text-primary-400">
            Hermes Agent
          </div>
          <div className="text-lg text-gray-400">团队协作面板</div>

          {/* Workspace Selector */}
          <WorkspaceSelector
            currentWorkspace={selectedWs}
            workspaces={localWorkspaces}
            onSelect={handleSelectWorkspace}
            onCreate={handleCreateWorkspace}
            onUpdate={handleUpdateWorkspace}
            onDelete={handleDeleteWorkspace}
          />
        </div>

        <div className="flex items-center gap-4">
          {/* Connection Status */}
          <div
            className={`flex items-center gap-2 px-3 py-1.5 rounded-full text-sm ${
              wsConnected
                ? "bg-green-500/20 text-green-400"
                : "bg-red-500/20 text-red-400"
            }`}
          >
            {wsConnected ? (
              <Wifi className="w-4 h-4" />
            ) : (
              <WifiOff className="w-4 h-4" />
            )}
            <span>{wsConnected ? "已连接" : "未连接"}</span>
          </div>

          {/* Reconnect Button */}
          {!wsConnected && onReconnect && (
            <button
              onClick={onReconnect}
              className="flex items-center gap-2 px-3 py-1.5 bg-primary-500/20 text-primary-400 rounded-lg hover:bg-primary-500/30 transition-colors"
            >
              <RefreshCw className="w-4 h-4" />
              <span>重连</span>
            </button>
          )}

          {/* Time */}
          <div className="text-gray-500 text-sm">
            {new Date().toLocaleString("zh-CN")}
          </div>
        </div>
      </div>
    </header>
  );
}
