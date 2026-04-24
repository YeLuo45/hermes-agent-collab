// 教育内容类型定义

// 颜色类型
export interface ColorItem {
  id: string;
  name: string;
  nameEn: string;
  hex: string;
  emoji?: string;
}

// 形状类型
export interface ShapeItem {
  id: string;
  name: string;
  nameEn: string;
  emoji: string;
  sides: number;
}

// 数字类型
export interface NumberItem {
  id: string;
  value: number;
  nameZh: string;
  nameEn: string;
  emoji: string;
}

// 字母类型
export interface LetterItem {
  id: string;
  letter: string;
  nameZh: string;
  nameEn: string;
  word: string;
  wordZh: string;
  emoji: string;
}

// 单词类型
export interface WordItem {
  id: string;
  word: string;
  translation: string;
  emoji: string;
  category: 'animal' | 'food' | 'color' | 'nature' | 'object' | 'action';
}

// 教育模块类型
export type EduModule = 'colors' | 'shapes' | 'numbers' | 'letters' | 'words';

// 教育项联合类型
export type EduItem = ColorItem | ShapeItem | NumberItem | LetterItem | WordItem;
