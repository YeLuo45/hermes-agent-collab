import { useState, useCallback } from "react";
import { useWebSocket } from "./useWebSocket";
import {
  Header,
  AgentPanel,
  TaskPanel,
  DetailPanel,
  StatusBar,
  SkillPanel,
  ChatModal,
  Skill,
} from "./components";
import { demoSkills } from "./components/SkillPanel";
import { demoWorkspaces } from "./components/WorkspaceSelector";
import { Task } from "./types";

function App() {
  const { state, wsConnected } = useWebSocket();
  const [selectedAgentId, setSelectedAgentId] = useState<string | null>(null);
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null);
  const [currentWorkspaceData, setCurrentWorkspaceData] = useState(demoWorkspaces[0]);
  const [skills, setSkills] = useState<Skill[]>(demoSkills);
  const [showSkills, setShowSkills] = useState(false);
  const [showChat, setShowChat] = useState(false);

  const handleSelectAgent = useCallback((agentId: string) => {
    setSelectedAgentId(agentId);
    setSelectedTaskId(null);
  }, []);

  const handleSelectTask = useCallback((taskId: string) => {
    setSelectedTaskId(taskId);
    setSelectedAgentId(null);
  }, []);

  const handleCloseDetail = useCallback(() => {
    setSelectedAgentId(null);
    setSelectedTaskId(null);
  }, []);

  const selectedAgent = selectedAgentId
    ? state.agents.find((a) => a.id === selectedAgentId)
    : null;

  const selectedTask = selectedTaskId
    ? state.tasks.find((t) => t.id === selectedTaskId)
    : null;

  // Create task with agent
  const handleCreateTask = useCallback(
    (taskData: {
      title: string;
      description: string;
      priority: Task["priority"];
      assignee_id: string;
    }) => {
      console.log("Create task:", taskData);
      // In real app, this would send via WebSocket
    },
    []
  );

  // Update skill
  const handleUpdateSkill = useCallback((skill: Skill) => {
    setSkills((prev) =>
      prev.map((s) => (s.id === skill.id ? skill : s))
    );
  }, []);

  // Delete skill
  const handleDeleteSkill = useCallback((id: string) => {
    setSkills((prev) => prev.filter((s) => s.id !== id));
  }, []);

  // Create skill
  const handleCreateSkill = useCallback(
    (skillData: Omit<Skill, "id">) => {
      const newSkill: Skill = {
        ...skillData,
        id: `skill-${Date.now()}`,
      };
      setSkills((prev) => [...prev, newSkill]);
    },
    []
  );

  return (
    <div className="h-screen flex flex-col bg-dark-500">
      {/* Header */}
      <Header
        wsConnected={wsConnected}
        currentWorkspace={currentWorkspaceData}
        onWorkspaceChange={setCurrentWorkspaceData}
      />

      {/* Main Content */}
      <div className="flex-1 flex overflow-hidden">
        {/* Left Panel - Agent Status */}
        <div className="w-80 bg-dark-300 border-r border-dark-100">
          <AgentPanel
            agents={state.agents}
            selectedAgentId={selectedAgentId}
            onSelectAgent={handleSelectAgent}
            currentWorkspaceId={currentWorkspaceData?.id}
            onAgentCreated={(agent) => console.log("Agent created:", agent)}
          />
        </div>

        {/* Center Panel - Task List */}
        <div className="flex-1 bg-dark-300">
          <TaskPanel
            tasks={state.tasks}
            agents={state.agents}
            selectedTaskId={selectedTaskId}
            onSelectTask={handleSelectTask}
            onCreateTask={handleCreateTask}
          />
        </div>

        {/* Right Panel - Detail */}
        <div className="w-96 border-l border-dark-100">
          <DetailPanel
            agent={selectedAgent || null}
            task={selectedTask || null}
            onClose={handleCloseDetail}
          />
        </div>
      </div>

      {/* Skills Panel (Slide-over) */}
      {showSkills && (
        <div className="fixed inset-0 z-50">
          <div
            className="absolute inset-0 bg-black/50"
            onClick={() => setShowSkills(false)}
          />
          <div className="absolute right-0 top-0 bottom-0 w-[400px] shadow-xl">
            <SkillPanel
              skills={skills}
              onUpdateSkill={handleUpdateSkill}
              onDeleteSkill={handleDeleteSkill}
              onCreateSkill={handleCreateSkill}
            />
          </div>
        </div>
      )}

      {/* Status Bar */}
      <StatusBar
        agents={state.agents}
        tasks={state.tasks}
        wsConnected={wsConnected}
        onOpenChat={() => setShowChat(true)}
      />

      {/* Chat Modal */}
      <ChatModal
        isOpen={showChat}
        onClose={() => setShowChat(false)}
        agents={state.agents}
        selectedAgentId={selectedAgentId}
      />
    </div>
  );
}

export default App;
