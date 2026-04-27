// Agent role types
export type AgentRole = "main" | "pm" | "dev";

// Agent status
export type AgentStatus =
  | "idle"
  | "thinking"
  | "working"
  | "waiting"
  | "error"
  | "offline";

// Agent entity
export interface Agent {
  id: string;
  name: string;
  role: AgentRole;
  status: AgentStatus;
  currentTask?: string;
  lastActive: number;
  avatar?: string;
  workspaceId?: string;
}

// Task status
export type TaskStatus =
  | "pending"
  | "in_progress"
  | "clarifying"
  | "prd_pending"
  | "approved"
  | "in_dev"
  | "in_acceptance"
  | "accepted"
  | "delivered"
  | "needs_revision"
  | "timeout_approved";

// Task entity
export interface Task {
  id: string;
  title: string;
  description: string;
  status: TaskStatus;
  owner: string; // agent id
  proposalId?: string;
  createdAt: number;
  updatedAt: number;
  priority: "low" | "medium" | "high" | "urgent";
  tags?: string[];
}

// WebSocket message types
export interface WSMessage {
  type:
    | "agent_update"
    | "task_update"
    | "proposal_update"
    | "ping"
    | "pong"
    | "subscribe"
    | "init";
  payload: unknown;
  timestamp: number;
}

// Store state
export interface AppState {
  agents: Agent[];
  tasks: Task[];
  selectedAgentId: string | null;
  selectedTaskId: string | null;
  wsConnected: boolean;
  lastUpdate: number;
}
