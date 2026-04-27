import { useState, useEffect, useRef } from "react";
import { Agent } from "../types";

interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  timestamp: number;
}

interface ChatModalProps {
  isOpen: boolean;
  onClose: () => void;
  agents: Agent[];
  selectedAgentId?: string | null;
}

export function ChatModal({
  isOpen,
  onClose,
  agents,
  selectedAgentId,
}: ChatModalProps) {
  const [chatAgentId, setChatAgentId] = useState<string | null>(
    selectedAgentId || null
  );
  const [messages, setMessages] = useState<Message[]>([]);
  const [inputValue, setInputValue] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // Auto-select first agent or the preselected one
  useEffect(() => {
    if (selectedAgentId) {
      setChatAgentId(selectedAgentId);
    } else if (agents.length > 0 && !chatAgentId) {
      setChatAgentId(agents[0].id);
    }
  }, [selectedAgentId, agents, chatAgentId]);

  // Scroll to bottom on new messages
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const currentAgent = agents.find((a) => a.id === chatAgentId);

  // Send message using vanilla JS fetch
  const sendMessage = async () => {
    console.log('[DEBUG] sendMessage called', { inputValue: inputValue.trim(), chatAgentId, isLoading });
    if (!inputValue.trim() || !chatAgentId || isLoading) {
      console.log('[DEBUG] sendMessage early return', { inputValueEmpty: !inputValue.trim(), noChatAgentId: !chatAgentId, loading: isLoading });
      return;
    }

    const userMessage: Message = {
      id: `msg-${Date.now()}-user`,
      role: "user",
      content: inputValue.trim(),
      timestamp: Date.now(),
    };

    setMessages((prev) => [...prev, userMessage]);
    const currentInput = inputValue;
    setInputValue("");
    setIsLoading(true);

    try {
      // Vanilla JS fetch - POST to /api/collab/agents/{id}/message
      const response = await fetch(`/api/collab/agents/${chatAgentId}/message`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ content: currentInput }),
      });

      if (response.ok) {
        const data = await response.json();
        const assistantMessage: Message = {
          id: `msg-${Date.now()}-assistant`,
          role: "assistant",
          content: data.content || "收到消息",
          timestamp: Date.now(),
        };
        setMessages((prev) => [...prev, assistantMessage]);
      } else {
        throw new Error("HTTP error");
      }
    } catch {
      // Simulate response if endpoint doesn't exist (vanilla JS mock)
      simulateResponse(currentInput);
    } finally {
      setIsLoading(false);
    }
  };

  // Simulate response when endpoint not available (vanilla JS fallback)
  const simulateResponse = (userInput: string) => {
    const responses = [
      `收到您的消息: "${userInput.substring(0, 50)}${userInput.length > 50 ? "..." : ""}"\n\n正在分析处理中...`,
      `好的，我已经理解您的问题。让我为您处理这个问题。`,
      `这是一个模拟响应，因为在开发环境中后端API不存在。`,
      `${currentAgent?.name || "Agent"} 正在思考中...\n\n基于您的问题，我建议:\n1. 首先检查相关配置\n2. 确认输入参数\n3. 重试操作`,
    ];

    const randomResponse =
      responses[Math.floor(Math.random() * responses.length)];

    setTimeout(() => {
      const assistantMessage: Message = {
        id: `msg-${Date.now()}-assistant`,
        role: "assistant",
        content: randomResponse,
        timestamp: Date.now(),
      };
      setMessages((prev) => [...prev, assistantMessage]);
    }, 800 + Math.random() * 1200);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  };

  const formatTime = (timestamp: number) => {
    return new Date(timestamp).toLocaleTimeString("zh-CN", {
      hour: "2-digit",
      minute: "2-digit",
    });
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/60" onClick={onClose} />

      {/* Modal */}
      <div className="relative w-[900px] h-[600px] bg-dark-300 rounded-xl shadow-2xl flex overflow-hidden border border-dark-100">
        {/* Left Panel - Agent List */}
        <div className="w-64 bg-dark-200 border-r border-dark-100 flex flex-col">
          {/* Header */}
          <div className="px-4 py-3 border-b border-dark-100">
            <h3 className="text-white font-medium">与 Agent 对话</h3>
            <p className="text-xs text-gray-500 mt-1">
              选择一个 Agent 开始交流
            </p>
          </div>

          {/* Agent List */}
          <div className="flex-1 overflow-y-auto p-2">
            {agents.map((agent) => (
              <div
                key={agent.id}
                onClick={() => {
                  console.log('[DEBUG] Agent clicked:', agent.id, agent.name);
                  setChatAgentId(agent.id);
                  setMessages([]);
                }}
                className={`p-3 rounded-lg cursor-pointer mb-1 transition-all ${
                  chatAgentId === agent.id
                    ? "bg-primary-500/20 border border-primary-500"
                    : "hover:bg-dark-100 border border-transparent"
                }`}
              >
                <div className="flex items-center gap-2">
                  <span className="text-xl">{agent.avatar || "🤖"}</span>
                  <div className="flex-1 min-w-0">
                    <div className="text-sm text-white font-medium truncate">
                      {agent.name}
                    </div>
                    <div className="text-xs text-gray-500 capitalize">
                      {agent.role}
                    </div>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Right Panel - Message Panel */}
        <div className="flex-1 flex flex-col">
          {/* Chat Header */}
          <div className="px-4 py-3 border-b border-dark-100 flex items-center justify-between">
            <div className="flex items-center gap-2">
              <span className="text-2xl">{currentAgent?.avatar || "🤖"}</span>
              <div>
                <div className="text-white font-medium">
                  {currentAgent?.name || "选择 Agent"}
                </div>
                <div className="text-xs text-gray-500">
                  {currentAgent ? "在线" : "请选择一个 Agent"}
                </div>
              </div>
            </div>
            <button
              onClick={onClose}
              className="p-2 hover:bg-dark-100 rounded-lg transition-colors"
            >
              <svg
                className="w-5 h-5 text-gray-400"
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M6 18L18 6M6 6l12 12"
                />
              </svg>
            </button>
          </div>

          {/* Messages */}
          <div className="flex-1 overflow-y-auto p-4 space-y-4">
            {messages.length === 0 && (
              <div className="h-full flex flex-col items-center justify-center text-gray-500">
                <div className="text-4xl mb-2">💬</div>
                <p>开始与 {currentAgent?.name || "Agent"} 对话吧</p>
              </div>
            )}

            {messages.map((msg) => (
              <div
                key={msg.id}
                className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}
              >
                <div
                  className={`max-w-[70%] rounded-lg px-4 py-2 ${
                    msg.role === "user"
                      ? "bg-primary-500 text-white"
                      : "bg-dark-100 text-gray-200"
                  }`}
                >
                  <div className="text-sm whitespace-pre-wrap">{msg.content}</div>
                  <div
                    className={`text-xs mt-1 ${
                      msg.role === "user" ? "text-primary-200" : "text-gray-500"
                    }`}
                  >
                    {formatTime(msg.timestamp)}
                  </div>
                </div>
              </div>
            ))}

            {isLoading && (
              <div className="flex justify-start">
                <div className="bg-dark-100 rounded-lg px-4 py-2">
                  <div className="flex items-center gap-1">
                    <div className="w-2 h-2 bg-gray-500 rounded-full animate-bounce" />
                    <div
                      className="w-2 h-2 bg-gray-500 rounded-full animate-bounce"
                      style={{ animationDelay: "0.2s" }}
                    />
                    <div
                      className="w-2 h-2 bg-gray-500 rounded-full animate-bounce"
                      style={{ animationDelay: "0.4s" }}
                    />
                  </div>
                </div>
              </div>
            )}

            <div ref={messagesEndRef} />
          </div>

          {/* Input */}
          <div className="p-4 border-t border-dark-100">
            <div className="flex gap-2">
              <textarea
                value={inputValue}
                onChange={(e) => setInputValue(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder={`给 ${currentAgent?.name || "Agent"} 发送消息...`}
                disabled={!currentAgent || isLoading}
                className="flex-1 bg-dark-200 text-white rounded-lg px-4 py-2 resize-none focus:outline-none focus:ring-2 focus:ring-primary-500 disabled:opacity-50"
                rows={1}
                style={{ maxHeight: "100px" }}
              />
              <button
                onClick={sendMessage}
                disabled={!inputValue.trim() || !currentAgent || isLoading}
                className="px-4 py-2 bg-primary-500 text-white rounded-lg hover:bg-primary-600 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
              >
                <svg
                  className="w-5 h-5"
                  fill="none"
                  stroke="currentColor"
                  viewBox="0 0 24 24"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8"
                  />
                </svg>
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
