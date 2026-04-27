import { useState } from "react";
import { Sparkles, Plus, Edit2, Trash2, X, Check, Loader2 } from "lucide-react";
import { skillApi } from "../api";

export interface Skill {
  id: string;
  name: string;
  description: string;
  category: string;
  enabled: boolean;
}

interface SkillPanelProps {
  agentId?: string;
  skills: Skill[];
  onUpdateSkill: (skill: Skill) => void;
  onDeleteSkill: (id: string) => void;
  onCreateSkill: (skill: Omit<Skill, "id">) => void;
}

// Demo skills
export const demoSkills: Skill[] = [
  {
    id: "skill-1",
    name: "代码审查",
    description: "自动审查代码质量和提出改进建议",
    category: "开发",
    enabled: true,
  },
  {
    id: "skill-2",
    name: "PRD 撰写",
    description: "生成专业的产品需求文档",
    category: "产品",
    enabled: true,
  },
  {
    id: "skill-3",
    name: "测试用例生成",
    description: "自动生成单元测试和集成测试用例",
    category: "开发",
    enabled: false,
  },
  {
    id: "skill-4",
    name: "API 文档生成",
    description: "从代码注释自动生成 API 文档",
    category: "文档",
    enabled: true,
  },
  {
    id: "skill-5",
    name: "性能分析",
    description: "分析系统性能瓶颈并提供优化建议",
    category: "运维",
    enabled: false,
  },
];

const CATEGORIES = ["全部", "开发", "产品", "设计", "文档", "运维", "其他"];

export function SkillPanel({
  skills,
  onUpdateSkill,
  onDeleteSkill,
  onCreateSkill,
}: SkillPanelProps) {
  const [categoryFilter, setCategoryFilter] = useState("全部");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [editForm, setEditForm] = useState<Partial<Skill>>({});
  const [newForm, setNewForm] = useState<Partial<Skill>>({
    name: "",
    description: "",
    category: "开发",
    enabled: true,
  });

  const filteredSkills =
    categoryFilter === "全部"
      ? skills
      : skills.filter((s) => s.category === categoryFilter);

  const handleStartEdit = (skill: Skill) => {
    setEditingId(skill.id);
    setEditForm({ ...skill });
  };

  const [deleteLoading, setDeleteLoading] = useState<string | null>(null);

  const handleSaveEdit = async () => {
    if (editingId && editForm.name) {
      // Call PATCH /skills/{id}
      const updatedSkill = { ...editForm, id: editingId } as Skill;
      const result = await skillApi.update(editingId, updatedSkill);
      if (result.success && result.data) {
        onUpdateSkill(result.data);
      }
      setEditingId(null);
      setEditForm({});
    }
  };

  const handleDelete = async (id: string) => {
    if (!confirm("确定要删除这个技能吗？")) return;
    setDeleteLoading(id);
    try {
      // Call DELETE /skills/{id}
      const result = await skillApi.delete(id);
      if (result.success) {
        onDeleteSkill(id);
      }
    } finally {
      setDeleteLoading(null);
    }
  };

  const handleCreate = () => {
    if (newForm.name && newForm.description) {
      onCreateSkill({
        name: newForm.name,
        description: newForm.description,
        category: newForm.category || "其他",
        enabled: true,
      });
      setNewForm({
        name: "",
        description: "",
        category: "开发",
        enabled: true,
      });
      setShowCreate(false);
    }
  };

  const toggleEnabled = (skill: Skill) => {
    onUpdateSkill({ ...skill, enabled: !skill.enabled });
  };

  return (
    <div className="h-full flex flex-col bg-dark-200">
      {/* Header */}
      <div className="px-4 py-3 border-b border-dark-100">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Sparkles className="w-5 h-5 text-primary-400" />
            <h2 className="text-lg font-medium text-white">技能库</h2>
          </div>
          <button
            onClick={() => setShowCreate(!showCreate)}
            className="p-1.5 hover:bg-dark-100 rounded-lg transition-colors"
          >
            {showCreate ? (
              <X className="w-5 h-5 text-gray-400" />
            ) : (
              <Plus className="w-5 h-5 text-primary-400" />
            )}
          </button>
        </div>

        {/* Category Filter */}
        <div className="flex gap-2 mt-3 overflow-x-auto pb-1">
          {CATEGORIES.map((cat) => (
            <button
              key={cat}
              onClick={() => setCategoryFilter(cat)}
              className={`px-3 py-1 text-sm rounded-full whitespace-nowrap transition-colors ${
                categoryFilter === cat
                  ? "bg-primary-500/20 text-primary-400"
                  : "bg-dark-100 text-gray-400 hover:text-white"
              }`}
            >
              {cat}
            </button>
          ))}
        </div>
      </div>

      {/* Create Form */}
      {showCreate && (
        <div className="p-4 border-b border-dark-100 bg-dark-100/50">
          <div className="space-y-3">
            <input
              type="text"
              placeholder="技能名称"
              value={newForm.name || ""}
              onChange={(e) => setNewForm({ ...newForm, name: e.target.value })}
              className="w-full px-3 py-2 bg-dark-300 border border-dark-100 rounded-lg text-white placeholder-gray-500 focus:outline-none focus:border-primary-500"
            />
            <input
              type="text"
              placeholder="技能描述"
              value={newForm.description || ""}
              onChange={(e) =>
                setNewForm({ ...newForm, description: e.target.value })
              }
              className="w-full px-3 py-2 bg-dark-300 border border-dark-100 rounded-lg text-white placeholder-gray-500 focus:outline-none focus:border-primary-500"
            />
            <select
              value={newForm.category || "开发"}
              onChange={(e) =>
                setNewForm({ ...newForm, category: e.target.value })
              }
              className="w-full px-3 py-2 bg-dark-300 border border-dark-100 rounded-lg text-white focus:outline-none focus:border-primary-500"
            >
              {CATEGORIES.filter((c) => c !== "全部").map((cat) => (
                <option key={cat} value={cat}>
                  {cat}
                </option>
              ))}
            </select>
            <div className="flex gap-2">
              <button
                onClick={handleCreate}
                className="flex items-center gap-1 px-4 py-2 bg-primary-500 text-white rounded-lg hover:bg-primary-600 transition-colors"
              >
                <Check className="w-4 h-4" />
                <span>创建</span>
              </button>
              <button
                onClick={() => {
                  setShowCreate(false);
                  setNewForm({
                    name: "",
                    description: "",
                    category: "开发",
                    enabled: true,
                  });
                }}
                className="px-4 py-2 text-gray-400 hover:text-white transition-colors"
              >
                取消
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Skill List */}
      <div className="flex-1 overflow-y-auto p-4 space-y-3">
        {filteredSkills.length === 0 ? (
          <div className="text-center text-gray-500 py-8">
            暂无技能
          </div>
        ) : (
          filteredSkills.map((skill) => (
            <div
              key={skill.id}
              className={`p-4 rounded-lg border transition-colors ${
                skill.enabled
                  ? "bg-dark-100 border-dark-100"
                  : "bg-dark-200 border-dark-200 opacity-60"
              }`}
            >
              {editingId === skill.id ? (
                <div className="space-y-3">
                  <input
                    type="text"
                    value={editForm.name || ""}
                    onChange={(e) =>
                      setEditForm({ ...editForm, name: e.target.value })
                    }
                    className="w-full px-3 py-2 bg-dark-300 border border-dark-100 rounded-lg text-white focus:outline-none focus:border-primary-500"
                  />
                  <input
                    type="text"
                    value={editForm.description || ""}
                    onChange={(e) =>
                      setEditForm({ ...editForm, description: e.target.value })
                    }
                    className="w-full px-3 py-2 bg-dark-300 border border-dark-100 rounded-lg text-white focus:outline-none focus:border-primary-500"
                  />
                  <select
                    value={editForm.category || "开发"}
                    onChange={(e) =>
                      setEditForm({ ...editForm, category: e.target.value })
                    }
                    className="w-full px-3 py-2 bg-dark-300 border border-dark-100 rounded-lg text-white focus:outline-none focus:border-primary-500"
                  >
                    {CATEGORIES.filter((c) => c !== "全部").map((cat) => (
                      <option key={cat} value={cat}>
                        {cat}
                      </option>
                    ))}
                  </select>
                  <div className="flex gap-2">
                    <button
                      onClick={handleSaveEdit}
                      className="flex items-center gap-1 px-3 py-1.5 bg-primary-500 text-white rounded-lg hover:bg-primary-600 transition-colors"
                    >
                      <Check className="w-4 h-4" />
                      <span>保存</span>
                    </button>
                    <button
                      onClick={() => setEditingId(null)}
                      className="px-3 py-1.5 text-gray-400 hover:text-white transition-colors"
                    >
                      取消
                    </button>
                  </div>
                </div>
              ) : (
                <>
                  <div className="flex items-start justify-between">
                    <div className="flex-1">
                      <div className="flex items-center gap-2">
                        <h3
                          className={`font-medium ${
                            skill.enabled ? "text-white" : "text-gray-400"
                          }`}
                        >
                          {skill.name}
                        </h3>
                        <span className="px-2 py-0.5 text-xs bg-dark-300 text-gray-500 rounded">
                          {skill.category}
                        </span>
                      </div>
                      <p
                        className={`text-sm mt-1 ${
                          skill.enabled ? "text-gray-400" : "text-gray-600"
                        }`}
                      >
                        {skill.description}
                      </p>
                    </div>
                    {/* Toggle */}
                    <button
                      onClick={() => toggleEnabled(skill)}
                      className={`relative w-10 h-5 rounded-full transition-colors ${
                        skill.enabled ? "bg-primary-500" : "bg-gray-600"
                      }`}
                    >
                      <span
                        className={`absolute top-0.5 w-4 h-4 bg-white rounded-full transition-transform ${
                          skill.enabled ? "left-5" : "left-0.5"
                        }`}
                      />
                    </button>
                  </div>
                  <div className="flex gap-2 mt-3 pt-3 border-t border-dark-300">
                    <button
                      onClick={() => handleStartEdit(skill)}
                      className="flex items-center gap-1 px-2 py-1 text-xs text-gray-400 hover:text-white hover:bg-dark-300 rounded transition-colors"
                    >
                      <Edit2 className="w-3 h-3" />
                      <span>编辑</span>
                    </button>
                    <button
                      onClick={() => handleDelete(skill.id)}
                      disabled={deleteLoading === skill.id}
                      className="flex items-center gap-1 px-2 py-1 text-xs text-gray-400 hover:text-red-400 hover:bg-dark-300 rounded transition-colors disabled:opacity-50"
                    >
                      {deleteLoading === skill.id ? (
                        <Loader2 className="w-3 h-3 animate-spin" />
                      ) : (
                        <Trash2 className="w-3 h-3" />
                      )}
                      <span>删除</span>
                    </button>
                  </div>
                </>
              )}
            </div>
          ))
        )}
      </div>
    </div>
  );
}
