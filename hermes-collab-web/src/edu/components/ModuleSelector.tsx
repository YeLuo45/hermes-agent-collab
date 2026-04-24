import type { EduModule } from '../types';

interface ModuleSelectorProps {
  currentModule: EduModule;
  onSelectModule: (module: EduModule) => void;
}

const modules: { id: EduModule; label: string; emoji: string; color: string }[] = [
  { id: 'colors', label: '颜色', emoji: '🎨', color: 'bg-red-500' },
  { id: 'shapes', label: '形状', emoji: '🔷', color: 'bg-purple-500' },
  { id: 'numbers', label: '数字', emoji: '🔢', color: 'bg-blue-500' },
  { id: 'letters', label: '字母', emoji: '🔤', color: 'bg-green-500' },
  { id: 'words', label: '单词', emoji: '📖', color: 'bg-orange-500' },
];

export function ModuleSelector({ currentModule, onSelectModule }: ModuleSelectorProps) {
  return (
    <div className="flex flex-wrap justify-center gap-4 p-4">
      {modules.map((mod) => (
        <button
          key={mod.id}
          onClick={() => onSelectModule(mod.id)}
          className={`
            flex items-center gap-3 px-6 py-4 rounded-2xl
            text-xl font-bold text-white
            transition-all duration-300 transform shadow-lg
            hover:scale-105 hover:shadow-xl
            active:scale-95
            ${currentModule === mod.id ? `${mod.color} ring-4 ring-yellow-300 ring-offset-2` : 'bg-gray-500'}
          `}
        >
          <span className="text-3xl">{mod.emoji}</span>
          <span>{mod.label}</span>
        </button>
      ))}
    </div>
  );
}
