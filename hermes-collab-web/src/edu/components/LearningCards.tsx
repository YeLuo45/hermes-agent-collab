import { useState } from 'react';
import type { ColorItem, ShapeItem, NumberItem, LetterItem, WordItem } from '../types';
import { useAnimation } from '../hooks';

// ==================== 颜色卡片 ====================
interface ColorCardProps {
  item: ColorItem;
  onClick?: () => void;
  isSelected?: boolean;
}

export function ColorCard({ item, onClick, isSelected }: ColorCardProps) {
  const { state, playSuccess } = useAnimation();
  const [showName, setShowName] = useState(false);

  const handleClick = () => {
    setShowName(true);
    playSuccess();
    onClick?.();
    setTimeout(() => setShowName(false), 1500);
  };

  return (
    <button
      onClick={handleClick}
      className={`
        relative w-28 h-28 rounded-3xl flex flex-col items-center justify-center
        transition-all duration-300 transform shadow-lg
        hover:scale-110 hover:shadow-xl
        active:scale-95
        ${isSelected ? 'ring-4 ring-yellow-400 ring-offset-2' : ''}
        ${state.feedback === 'success' ? 'animate-bounce' : ''}
        ${state.feedback === 'error' ? 'animate-shake' : ''}
      `}
      style={{ backgroundColor: item.hex }}
    >
      <span className="text-4xl mb-1">{item.emoji}</span>
      {showName && (
        <div className="absolute inset-0 flex flex-col items-center justify-center bg-black/40 rounded-3xl">
          <span className="text-white text-xl font-bold drop-shadow-lg">{item.name}</span>
          <span className="text-white/80 text-sm mt-1">{item.nameEn}</span>
        </div>
      )}
    </button>
  );
}

// ==================== 形状卡片 ====================
interface ShapeCardProps {
  item: ShapeItem;
  onClick?: () => void;
  isSelected?: boolean;
}

export function ShapeCard({ item, onClick, isSelected }: ShapeCardProps) {
  const { state, playSuccess } = useAnimation();
  const [showName, setShowName] = useState(false);

  const handleClick = () => {
    setShowName(true);
    playSuccess();
    onClick?.();
    setTimeout(() => setShowName(false), 1500);
  };

  return (
    <button
      onClick={handleClick}
      className={`
        w-32 h-32 rounded-3xl bg-gradient-to-br from-purple-100 to-pink-100
        flex flex-col items-center justify-center
        transition-all duration-300 transform shadow-lg
        hover:scale-110 hover:shadow-xl
        active:scale-95
        ${isSelected ? 'ring-4 ring-purple-400 ring-offset-2' : ''}
        ${state.feedback === 'success' ? 'animate-bounce' : ''}
      `}
    >
      <span className="text-6xl mb-1 transition-transform duration-300 hover:scale-125">
        {item.emoji}
      </span>
      {showName && (
        <div className="absolute inset-0 flex flex-col items-center justify-center bg-purple-500/80 rounded-3xl">
          <span className="text-white text-xl font-bold">{item.name}</span>
          <span className="text-white/80 text-sm mt-1">{item.nameEn}</span>
        </div>
      )}
    </button>
  );
}

// ==================== 数字卡片 ====================
interface NumberCardProps {
  item: NumberItem;
  onClick?: () => void;
  isSelected?: boolean;
  showWord?: boolean;
}

export function NumberCard({ item, onClick, isSelected }: NumberCardProps) {
  const { state, playSuccess } = useAnimation();
  const [showDetails, setShowDetails] = useState(false);

  const handleClick = () => {
    setShowDetails(true);
    playSuccess();
    onClick?.();
    setTimeout(() => setShowDetails(false), 1500);
  };

  return (
    <button
      onClick={handleClick}
      className={`
        w-36 h-36 rounded-3xl bg-gradient-to-br from-blue-100 to-cyan-100
        flex flex-col items-center justify-center
        transition-all duration-300 transform shadow-lg
        hover:scale-110 hover:shadow-xl
        active:scale-95
        ${isSelected ? 'ring-4 ring-blue-400 ring-offset-2' : ''}
        ${state.feedback === 'success' ? 'animate-bounce' : ''}
      `}
    >
      <span className="text-5xl mb-1">{item.emoji}</span>
      <span className="text-3xl font-bold text-blue-600">{item.value}</span>
      {showDetails && (
        <div className="absolute inset-0 flex flex-col items-center justify-center bg-blue-500/90 rounded-3xl">
          <span className="text-white text-3xl font-bold">{item.nameZh}</span>
          <span className="text-white/80 text-sm mt-1">{item.nameEn}</span>
        </div>
      )}
    </button>
  );
}

// ==================== 字母卡片 ====================
interface LetterCardProps {
  item: LetterItem;
  onClick?: () => void;
  isSelected?: boolean;
}

export function LetterCard({ item, onClick, isSelected }: LetterCardProps) {
  const { state, playSuccess } = useAnimation();
  const [showDetails, setShowDetails] = useState(false);

  const handleClick = () => {
    setShowDetails(true);
    playSuccess();
    onClick?.();
    setTimeout(() => setShowDetails(false), 2000);
  };

  return (
    <button
      onClick={handleClick}
      className={`
        w-40 h-44 rounded-3xl bg-gradient-to-br from-green-100 to-emerald-100
        flex flex-col items-center justify-center
        transition-all duration-300 transform shadow-lg
        hover:scale-110 hover:shadow-xl
        active:scale-95
        ${isSelected ? 'ring-4 ring-green-400 ring-offset-2' : ''}
        ${state.feedback === 'success' ? 'animate-bounce' : ''}
      `}
    >
      <span className="text-6xl font-bold text-green-600 mb-1">{item.letter}</span>
      <span className="text-sm text-green-500 mb-2">{item.nameEn}</span>
      {showDetails && (
        <div className="absolute inset-0 flex flex-col items-center justify-center bg-green-500/95 rounded-3xl">
          <span className="text-5xl mb-2">{item.emoji}</span>
          <span className="text-white text-lg font-bold">{item.word}</span>
          <span className="text-white/80 text-sm mt-1">{item.wordZh}</span>
        </div>
      )}
    </button>
  );
}

// ==================== 单词卡片 ====================
interface WordCardProps {
  item: WordItem;
  onClick?: () => void;
  isSelected?: boolean;
  showTranslation?: boolean;
}

export function WordCard({ item, onClick, isSelected, showTranslation = false }: WordCardProps) {
  const { state, playSuccess } = useAnimation();
  const [showDetails, setShowDetails] = useState(false);

  const handleClick = () => {
    setShowDetails(true);
    playSuccess();
    onClick?.();
    setTimeout(() => setShowDetails(false), 2000);
  };

  const categoryColors: Record<string, string> = {
    animal: 'from-orange-100 to-yellow-100',
    food: 'from-red-100 to-pink-100',
    color: 'from-purple-100 to-violet-100',
    nature: 'from-green-100 to-teal-100',
    object: 'from-blue-100 to-indigo-100',
    action: 'from-rose-100 to-red-100',
  };

  return (
    <button
      onClick={handleClick}
      className={`
        w-44 h-48 rounded-3xl bg-gradient-to-br ${categoryColors[item.category]}
        flex flex-col items-center justify-center
        transition-all duration-300 transform shadow-lg
        hover:scale-110 hover:shadow-xl
        active:scale-95
        ${isSelected ? 'ring-4 ring-rose-400 ring-offset-2' : ''}
        ${state.feedback === 'success' ? 'animate-bounce' : ''}
      `}
    >
      <span className="text-6xl mb-2">{item.emoji}</span>
      <span className="text-xl font-bold text-gray-700">{item.word}</span>
      {showTranslation && (
        <span className="text-sm text-gray-500 mt-1">{item.translation}</span>
      )}
      {showDetails && (
        <div className="absolute inset-0 flex flex-col items-center justify-center bg-white/95 rounded-3xl shadow-inner">
          <span className="text-6xl mb-2">{item.emoji}</span>
          <span className="text-2xl font-bold text-gray-800">{item.word}</span>
          <span className="text-lg text-gray-600 mt-2">{item.translation}</span>
        </div>
      )}
    </button>
  );
}
