import { useState } from 'react';
import type { EduModule } from '../types';
import { eduData } from '../data/content';
import { ModuleSelector } from './ModuleSelector';
import { LearningGrid } from './LearningGrid';

export function EducationView() {
  const [currentModule, setCurrentModule] = useState<EduModule>('colors');
  const [selectedItemId, setSelectedItemId] = useState<string | undefined>();

  const moduleTitles: Record<EduModule, { zh: string; en: string; emoji: string }> = {
    colors: { zh: '认识颜色', en: 'Learn Colors', emoji: '🎨' },
    shapes: { zh: '认识形状', en: 'Learn Shapes', emoji: '🔷' },
    numbers: { zh: '认识数字', en: 'Learn Numbers', emoji: '🔢' },
    letters: { zh: '认识字母', en: 'Learn Letters', emoji: '🔤' },
    words: { zh: '学单词', en: 'Learn Words', emoji: '📖' },
  };

  const currentData = eduData[currentModule];

  return (
    <div className="min-h-screen bg-gradient-to-br from-blue-50 via-purple-50 to-pink-50">
      {/* 标题区域 */}
      <div className="bg-white/80 backdrop-blur-sm shadow-md py-6">
        <div className="text-center">
          <h1 className="text-4xl font-bold text-gray-800 flex items-center justify-center gap-3">
            <span className="text-5xl">{moduleTitles[currentModule].emoji}</span>
            <span>{moduleTitles[currentModule].zh}</span>
            <span className="text-xl text-gray-500 ml-2">
              {moduleTitles[currentModule].en}
            </span>
          </h1>
        </div>
      </div>

      {/* 模块选择器 */}
      <ModuleSelector
        currentModule={currentModule}
        onSelectModule={setCurrentModule}
      />

      {/* 学习内容网格 */}
      <LearningGrid
        module={currentModule}
        data={currentData}
        selectedId={selectedItemId}
        onSelectItem={setSelectedItemId}
      />

      {/* 底部提示 */}
      <div className="fixed bottom-0 left-0 right-0 bg-white/90 backdrop-blur-sm py-3 text-center">
        <p className="text-gray-500 text-lg">
          👆 点击卡片查看更多信息
        </p>
      </div>
    </div>
  );
}
