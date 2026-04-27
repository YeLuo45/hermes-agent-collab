// API utilities for Hermes Agent Collaboration Web

const API_BASE = '/api/collab';

interface ApiResponse<T> {
  success: boolean;
  data?: T;
  error?: string;
}

async function request<T>(
  method: string,
  path: string,
  body?: unknown
): Promise<ApiResponse<T>> {
  try {
    const response = await fetch(`${API_BASE}${path}`, {
      method,
      headers: {
        'Content-Type': 'application/json',
      },
      body: body ? JSON.stringify(body) : undefined,
    });

    if (!response.ok) {
      return {
        success: false,
        error: `HTTP ${response.status}: ${response.statusText}`,
      };
    }

    const data = await response.json();
    return { success: true, data };
  } catch (error) {
    return {
      success: false,
      error: error instanceof Error ? error.message : 'Network error',
    };
  }
}

// Skill API
export interface Skill {
  id: string;
  name: string;
  description: string;
  category: string;
  enabled: boolean;
}

export const skillApi = {
  // PATCH /skills/{id} - Update skill
  update: (id: string, skill: Partial<Skill>): Promise<ApiResponse<Skill>> => {
    return request<Skill>('PATCH', `/skills/${id}`, skill);
  },

  // DELETE /skills/{id} - Delete skill
  delete: (id: string): Promise<ApiResponse<{ id: string }>> => {
    return request<{ id: string }>('DELETE', `/skills/${id}`);
  },

  // POST /skills - Create skill
  create: (skill: Omit<Skill, 'id'>): Promise<ApiResponse<Skill>> => {
    return request<Skill>('POST', '/skills', skill);
  },

  // GET /skills - List skills
  list: (): Promise<ApiResponse<Skill[]>> => {
    return request<Skill[]>('GET', '/skills');
  },
};

// Agent API
// Note: Backend returns agent_id, frontend expects id - transformation happens at call site
export interface Agent {
  id: string;
  name: string;
  role: 'main' | 'pm' | 'dev';
  status: 'idle' | 'thinking' | 'working' | 'waiting' | 'error' | 'offline';
  workspaceId?: string;
  currentTask?: string;
  lastActive: number;
  avatar?: string;
}

export const agentApi = {
  // POST /agents - Register agent
  register: (agent: { name: string; role: string; workspaceId?: string }): Promise<ApiResponse<Agent>> => {
    return request<any>('POST', '/agents', {
      name: agent.name,
      role: agent.role,
      description: '',
      skills: [],
      workspace_id: agent.workspaceId
    }).then(res => {
      if (res.success && res.data) {
        res.data = {
          id: res.data.agent_id,
          name: res.data.name,
          role: res.data.role,
          status: 'idle' as const,
          lastActive: Date.now()
        };
      }
      return res;
    });
  },

  // PATCH /agents/{id} - Update agent
  update: (id: string, agent: { name?: string; role?: string; status?: string }): Promise<ApiResponse<Agent>> => {
    return request<any>('PATCH', `/agents/${id}`, agent).then(res => {
      if (res.success && res.data) {
        res.data = {
          id: res.data.agent_id,
          name: res.data.name,
          role: res.data.role,
          status: 'idle' as const,
          lastActive: Date.now()
        };
      }
      return res;
    });
  },

  // DELETE /agents/{id} - Delete agent
  delete: (id: string): Promise<ApiResponse<{ id: string }>> => {
    return request<{ id: string }>('DELETE', `/agents/${id}`);
  },

  // GET /agents - List all agents
  list: (): Promise<ApiResponse<Agent[]>> => {
    return request<any>('GET', '/agents').then(res => {
      if (res.success && res.data) {
        // Transform backend response: {agents: [...]} -> Agent[]
        const agents = res.data.agents || [];
        res.data = agents.map((a: any) => ({
          id: a.agent_id,
          name: a.name,
          role: a.role,
          status: (a.status === 'online' ? 'idle' : a.status) as Agent['status'],
          workspaceId: a.workspace_id,
          currentTask: a.current_task_id,
          lastActive: Date.now(),
          avatar: a.avatar
        }));
      }
      return res;
    });
  },
};

// Workspace API
export interface Workspace {
  id: string;
  name: string;
  description?: string;
  agentCount: number;
  taskCount: number;
  createdAt: number;
}

export const workspaceApi = {
  // DELETE /workspaces/{id} - Delete workspace
  delete: (id: string): Promise<ApiResponse<{ id: string }>> => {
    return request<{ id: string }>('DELETE', `/workspaces/${id}`);
  },

  // PATCH /workspaces/{id} - Update workspace (rename)
  update: (id: string, data: { name?: string; description?: string }): Promise<ApiResponse<Workspace>> => {
    return request<Workspace>('PATCH', `/workspaces/${id}`, data);
  },

  // POST /workspaces - Create workspace
  create: (workspace: Omit<Workspace, 'id' | 'agentCount' | 'taskCount' | 'createdAt'>): Promise<ApiResponse<Workspace>> => {
    return request<Workspace>('POST', '/workspaces', workspace);
  },

  // GET /workspaces - List workspaces
  list: (): Promise<ApiResponse<Workspace[]>> => {
    return request<Workspace[]>('GET', '/workspaces');
  },
};
