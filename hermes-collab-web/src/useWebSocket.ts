import { useEffect, useRef, useCallback, useState } from "react";
import { Agent, Task, AppState } from "./types";
import {
  initialAgents,
  initialTasks,
} from "./store";

// Dynamically construct WebSocket URL based on current page location
const WS_PROTOCOL = window.location.protocol === "https:" ? "wss:" : "ws:";
const WS_HOST = window.location.host;
const WS_URL = `${WS_PROTOCOL}//${WS_HOST}/api/collab/ws`;
const RECONNECT_DELAY = 3000;
const PING_INTERVAL = 30000;

interface UseWebSocketReturn {
  state: AppState;
  wsConnected: boolean;
  updateAgentStatus: (
    agentId: string,
    status: Agent["status"],
    currentTask?: string
  ) => void;
  updateTaskStatus: (taskId: string, status: Task["status"]) => void;
}

export function useWebSocket(): UseWebSocketReturn {
  const [state, setState] = useState<AppState>({
    agents: initialAgents,
    tasks: initialTasks,
    selectedAgentId: null,
    selectedTaskId: null,
    wsConnected: false,
    lastUpdate: Date.now(),
  });
  const [wsConnected, setWsConnected] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<number | null>(null);
  const pingIntervalRef = useRef<number | null>(null);

  const connect = useCallback(() => {
    try {
      const ws = new WebSocket(WS_URL);
      wsRef.current = ws;

      ws.onopen = () => {
        console.log("WebSocket connected");
        setWsConnected(true);
        setState((prev) => ({ ...prev, wsConnected: true }));
        // Subscribe to updates
        ws.send(
          JSON.stringify({
            type: "subscribe",
            payload: { channels: ["agents", "tasks", "proposals"] },
            timestamp: Date.now(),
          })
        );
        // Start ping interval
        pingIntervalRef.current = window.setInterval(() => {
          if (ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({ type: "ping", timestamp: Date.now() }));
          }
        }, PING_INTERVAL);
      };

      ws.onmessage = (event) => {
        try {
          const message = JSON.parse(event.data);
          handleMessage(message);
        } catch (e) {
          console.error("Failed to parse message:", e);
        }
      };

      ws.onerror = (error) => {
        console.error("WebSocket error:", error);
        setWsConnected(false);
      };

      ws.onclose = () => {
        console.log("WebSocket disconnected");
        setWsConnected(false);
        if (pingIntervalRef.current) {
          clearInterval(pingIntervalRef.current);
        }
        // Attempt reconnection
        reconnectTimeoutRef.current = window.setTimeout(connect, RECONNECT_DELAY);
      };
    } catch (e) {
      console.error("Failed to create WebSocket:", e);
      setWsConnected(false);
      reconnectTimeoutRef.current = window.setTimeout(connect, RECONNECT_DELAY);
    }
  }, []);

  const handleMessage = useCallback((message: { type: string; payload: unknown }) => {
    // Transform backend agent_id to id
    const transformAgent = (a: any): Agent => ({
      id: a.id || a.agent_id,
      name: a.name,
      role: a.role,
      status: a.status === 'online' ? 'idle' : (a.status || 'idle'),
      workspaceId: a.workspace_id,
      currentTask: a.current_task_id,
      lastActive: a.last_active || Date.now(),
      avatar: a.avatar,
    });

    switch (message.type) {
      case "init":
        // Handle initial state
        if (message.payload && typeof message.payload === "object") {
          const payload = message.payload as { agents?: any[]; tasks?: Task[] };
          setState((prev) => ({
            ...prev,
            agents: (payload.agents || prev.agents).map(transformAgent),
            tasks: payload.tasks || prev.tasks,
            lastUpdate: Date.now(),
          }));
        }
        break;

      case "agent_update":
        // Handle agent update
        const updatePayload = message.payload as any;
        setState((prev) => ({
          ...prev,
          agents: prev.agents.map((agent) =>
            agent.id === (updatePayload.id || updatePayload.agent_id)
              ? ({ ...agent, ...transformAgent(updatePayload) } as Agent)
              : agent
          ),
          lastUpdate: Date.now(),
        }));
        break;

      case "task_update":
        // Handle task update
        setState((prev) => ({
          ...prev,
          tasks: prev.tasks.map((task) =>
            task.id === (message.payload as Task).id
              ? ({ ...task, ...(message.payload as Partial<Task>) } as Task)
              : task
          ),
          lastUpdate: Date.now(),
        }));
        break;

      case "pong":
        // Heartbeat response
        break;

      default:
        console.log("Unknown message type:", message.type);
    }
  }, []);

  const updateAgentStatus = useCallback(
    (
      agentId: string,
      status: Agent["status"],
      currentTask?: string
    ) => {
      const updatedAgents = state.agents.map((agent) =>
        agent.id === agentId
          ? {
              ...agent,
              status,
              currentTask,
              lastActive: Date.now(),
            }
          : agent
      );
      setState((prev) => ({ ...prev, agents: updatedAgents }));

      // Send update via WebSocket if connected
      if (wsRef.current?.readyState === WebSocket.OPEN) {
        wsRef.current.send(
          JSON.stringify({
            type: "agent_update",
            payload: {
              id: agentId,
              status,
              currentTask,
              lastActive: Date.now(),
            },
            timestamp: Date.now(),
          })
        );
      }
    },
    [state.agents]
  );

  const updateTaskStatus = useCallback(
    (taskId: string, status: Task["status"]) => {
      const updatedTasks = state.tasks.map((task) =>
        task.id === taskId ? { ...task, status, updatedAt: Date.now() } : task
      );
      setState((prev) => ({ ...prev, tasks: updatedTasks }));

      // Send update via WebSocket if connected
      if (wsRef.current?.readyState === WebSocket.OPEN) {
        wsRef.current.send(
          JSON.stringify({
            type: "task_update",
            payload: { id: taskId, status, updatedAt: Date.now() },
            timestamp: Date.now(),
          })
        );
      }
    },
    [state.tasks]
  );

  useEffect(() => {
    // Try to connect, but don't fail if no server
    connect();

    return () => {
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current);
      }
      if (pingIntervalRef.current) {
        clearInterval(pingIntervalRef.current);
      }
      if (wsRef.current) {
        wsRef.current.close();
      }
    };
  }, [connect]);

  return {
    state,
    wsConnected,
    updateAgentStatus,
    updateTaskStatus,
  };
}
