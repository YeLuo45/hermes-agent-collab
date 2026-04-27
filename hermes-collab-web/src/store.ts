import { Agent, Task } from "./types";

// Generate unique IDs
export function generateId(): string {
  return Math.random().toString(36).substring(2, 11);
}

// Initial demo agents
export const initialAgents: Agent[] = [
  {
    id: "agent-main",
    name: "小墨 (Main)",
    role: "main",
    status: "idle",
    currentTask: undefined,
    lastActive: Date.now(),
    avatar: "👑",
  },
  {
    id: "agent-pm",
    name: "PM Agent",
    role: "pm",
    status: "working",
    currentTask: "P-20250419-001 PRD 确认",
    lastActive: Date.now() - 120000,
    avatar: "📋",
  },
  {
    id: "agent-dev",
    name: "Dev Agent",
    role: "dev",
    status: "waiting",
    currentTask: "P-20250418-003 等待验收",
    lastActive: Date.now() - 300000,
    avatar: "💻",
  },
];

// Initial demo tasks
export const initialTasks: Task[] = [
  {
    id: "task-1",
    title: "用户认证模块优化",
    description: "优化现有认证流程，增加双因素认证支持",
    status: "in_dev",
    owner: "agent-dev",
    proposalId: "P-20250418-003",
    createdAt: Date.now() - 86400000,
    updatedAt: Date.now() - 300000,
    priority: "high",
    tags: ["认证", "安全"],
  },
  {
    id: "task-2",
    title: " PRD: 聊天机器人功能增强",
    description: "为聊天机器人增加语音识别和情感分析能力",
    status: "clarifying",
    owner: "agent-pm",
    proposalId: "P-20250419-001",
    createdAt: Date.now() - 43200000,
    updatedAt: Date.now() - 120000,
    priority: "medium",
    tags: ["AI", "聊天"],
  },
  {
    id: "task-3",
    title: "数据库性能优化",
    description: "优化查询性能，添加缓存层",
    status: "in_acceptance",
    owner: "agent-dev",
    proposalId: "P-20250417-002",
    createdAt: Date.now() - 172800000,
    updatedAt: Date.now() - 600000,
    priority: "high",
    tags: ["数据库", "性能"],
  },
  {
    id: "task-4",
    title: "移动端适配",
    description: "Web UI 响应式设计优化",
    status: "pending",
    owner: "agent-main",
    createdAt: Date.now() - 21600000,
    updatedAt: Date.now() - 21600000,
    priority: "medium",
    tags: ["UI", "移动端"],
  },
  {
    id: "task-5",
    title: "API 文档自动生成",
    description: "实现 Swagger/OpenAPI 文档自动生成",
    status: "prd_pending",
    owner: "agent-pm",
    proposalId: "P-20250419-002",
    createdAt: Date.now() - 3600000,
    updatedAt: Date.now() - 1800000,
    priority: "low",
    tags: ["文档", "API"],
  },
];

// Status display configurations
export const statusConfig: Record<
  string,
  { label: string; color: string; bgColor: string }
> = {
  idle: { label: "空闲", color: "text-gray-400", bgColor: "bg-gray-400" },
  thinking: {
    label: "思考中",
    color: "text-yellow-400",
    bgColor: "bg-yellow-400",
  },
  working: {
    label: "工作中",
    color: "text-green-400",
    bgColor: "bg-green-400",
  },
  waiting: { label: "等待中", color: "text-blue-400", bgColor: "bg-blue-400" },
  error: { label: "错误", color: "text-red-400", bgColor: "bg-red-400" },
  offline: { label: "离线", color: "text-gray-500", bgColor: "bg-gray-500" },
};

export const taskStatusConfig: Record<
  string,
  { label: string; color: string; bgColor: string }
> = {
  pending: {
    label: "待处理",
    color: "text-gray-400",
    bgColor: "bg-gray-400",
  },
  in_progress: {
    label: "进行中",
    color: "text-blue-400",
    bgColor: "bg-blue-400",
  },
  clarifying: {
    label: "澄清中",
    color: "text-yellow-400",
    bgColor: "bg-yellow-400",
  },
  prd_pending: {
    label: "PRD待确认",
    color: "text-orange-400",
    bgColor: "bg-orange-400",
  },
  approved: {
    label: "已批准",
    color: "text-cyan-400",
    bgColor: "bg-cyan-400",
  },
  in_dev: {
    label: "开发中",
    color: "text-purple-400",
    bgColor: "bg-purple-400",
  },
  in_acceptance: {
    label: "验收中",
    color: "text-pink-400",
    bgColor: "bg-pink-400",
  },
  accepted: {
    label: "已验收",
    color: "text-green-400",
    bgColor: "bg-green-400",
  },
  delivered: {
    label: "已交付",
    color: "text-emerald-400",
    bgColor: "bg-emerald-400",
  },
  needs_revision: {
    label: "需返修",
    color: "text-red-400",
    bgColor: "bg-red-400",
  },
  timeout_approved: {
    label: "超时通过",
    color: "text-amber-400",
    bgColor: "bg-amber-400",
  },
};

export const priorityConfig: Record<
  string,
  { label: string; color: string }
> = {
  low: { label: "低", color: "text-gray-400" },
  medium: { label: "中", color: "text-blue-400" },
  high: { label: "高", color: "text-orange-400" },
  urgent: { label: "紧急", color: "text-red-400" },
};

// Format relative time
export function formatRelativeTime(timestamp: number): string {
  const now = Date.now();
  const diff = now - timestamp;
  const seconds = Math.floor(diff / 1000);
  const minutes = Math.floor(seconds / 60);
  const hours = Math.floor(minutes / 60);
  const days = Math.floor(hours / 24);

  if (seconds < 60) return "刚刚";
  if (minutes < 60) return `${minutes}分钟前`;
  if (hours < 24) return `${hours}小时前`;
  return `${days}天前`;
}
