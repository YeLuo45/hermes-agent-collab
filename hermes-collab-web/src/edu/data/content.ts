import type { ColorItem, ShapeItem, NumberItem, LetterItem, WordItem } from '../types';

// 颜色数据
export const colorsData: ColorItem[] = [
  { id: 'red', name: '红色', nameEn: 'Red', hex: '#FF4444', emoji: '🔴' },
  { id: 'orange', name: '橙色', nameEn: 'Orange', hex: '#FF8800', emoji: '🟠' },
  { id: 'yellow', name: '黄色', nameEn: 'Yellow', hex: '#FFDD00', emoji: '🟡' },
  { id: 'green', name: '绿色', nameEn: 'Green', hex: '#44BB44', emoji: '🟢' },
  { id: 'blue', name: '蓝色', nameEn: 'Blue', hex: '#4488FF', emoji: '🔵' },
  { id: 'purple', name: '紫色', nameEn: 'Purple', hex: '#AA44FF', emoji: '🟣' },
  { id: 'pink', name: '粉色', nameEn: 'Pink', hex: '#FF66AA', emoji: '💗' },
  { id: 'brown', name: '棕色', nameEn: 'Brown', hex: '#8B4513', emoji: '🟤' },
  { id: 'black', name: '黑色', nameEn: 'Black', hex: '#222222', emoji: '⚫' },
  { id: 'white', name: '白色', nameEn: 'White', hex: '#FFFFFF', emoji: '⚪' },
];

// 形状数据
export const shapesData: ShapeItem[] = [
  { id: 'circle', name: '圆形', nameEn: 'Circle', emoji: '⭕', sides: 0 },
  { id: 'square', name: '正方形', nameEn: 'Square', emoji: '⬜', sides: 4 },
  { id: 'triangle', name: '三角形', nameEn: 'Triangle', emoji: '🔺', sides: 3 },
  { id: 'rectangle', name: '长方形', nameEn: 'Rectangle', emoji: '▬', sides: 4 },
  { id: 'star', name: '星形', nameEn: 'Star', emoji: '⭐', sides: 5 },
  { id: 'heart', name: '心形', nameEn: 'Heart', emoji: '❤️', sides: 0 },
  { id: 'diamond', name: '菱形', nameEn: 'Diamond', emoji: '💎', sides: 4 },
  { id: 'oval', name: '椭圆形', nameEn: 'Oval', emoji: '🥚', sides: 0 },
];

// 数字数据
export const numbersData: NumberItem[] = [
  { id: '0', value: 0, nameZh: '零', nameEn: 'Zero', emoji: '0️⃣' },
  { id: '1', value: 1, nameZh: '一', nameEn: 'One', emoji: '1️⃣' },
  { id: '2', value: 2, nameZh: '二', nameEn: 'Two', emoji: '2️⃣' },
  { id: '3', value: 3, nameZh: '三', nameEn: 'Three', emoji: '3️⃣' },
  { id: '4', value: 4, nameZh: '四', nameEn: 'Four', emoji: '4️⃣' },
  { id: '5', value: 5, nameZh: '五', nameEn: 'Five', emoji: '5️⃣' },
  { id: '6', value: 6, nameZh: '六', nameEn: 'Six', emoji: '6️⃣' },
  { id: '7', value: 7, nameZh: '七', nameEn: 'Seven', emoji: '7️⃣' },
  { id: '8', value: 8, nameZh: '八', nameEn: 'Eight', emoji: '8️⃣' },
  { id: '9', value: 9, nameZh: '九', nameEn: 'Nine', emoji: '9️⃣' },
  { id: '10', value: 10, nameZh: '十', nameEn: 'Ten', emoji: '🔟' },
];

// 字母数据
export const lettersData: LetterItem[] = [
  { id: 'a', letter: 'A', nameZh: 'ei', nameEn: 'A', word: 'Apple', wordZh: '苹果', emoji: '🍎' },
  { id: 'b', letter: 'B', nameZh: 'bi', nameEn: 'B', word: 'Ball', wordZh: '球', emoji: '⚽' },
  { id: 'c', letter: 'C', nameZh: 'si', nameEn: 'C', word: 'Cat', wordZh: '猫', emoji: '🐱' },
  { id: 'd', letter: 'D', nameZh: 'di', nameEn: 'D', word: 'Dog', wordZh: '狗', emoji: '🐕' },
  { id: 'e', letter: 'E', nameZh: 'i', nameEn: 'E', word: 'Elephant', wordZh: '大象', emoji: '🐘' },
  { id: 'f', letter: 'F', nameZh: 'ai', nameEn: 'F', word: 'Fish', wordZh: '鱼', emoji: '🐟' },
  { id: 'g', letter: 'G', nameZh: 'ji', nameEn: 'G', word: 'Grape', wordZh: '葡萄', emoji: '🍇' },
  { id: 'h', letter: 'H', nameZh: 'aiq', nameEn: 'H', word: 'Hat', wordZh: '帽子', emoji: '🎩' },
  { id: 'i', letter: 'I', nameZh: 'ai', nameEn: 'I', word: 'Ice cream', wordZh: '冰淇淋', emoji: '🍦' },
  { id: 'j', letter: 'J', nameZh: 'jie', nameEn: 'J', word: 'Juice', wordZh: '果汁', emoji: '🧃' },
  { id: 'k', letter: 'K', nameZh: 'kei', nameEn: 'K', word: 'Kite', wordZh: '风筝', emoji: '🪁' },
  { id: 'l', letter: 'L', nameZh: 'ai', nameEn: 'L', word: 'Lion', wordZh: '狮子', emoji: '🦁' },
  { id: 'm', letter: 'M', nameZh: 'ai', nameEn: 'M', word: 'Moon', wordZh: '月亮', emoji: '🌙' },
  { id: 'n', letter: 'N', nameZh: 'ai', nameEn: 'N', word: 'Nest', wordZh: '鸟巢', emoji: '🪺' },
  { id: 'o', letter: 'O', nameZh: 'ou', nameEn: 'O', word: 'Orange', wordZh: '橙子', emoji: '🍊' },
  { id: 'p', letter: 'P', nameZh: 'pi', nameEn: 'P', word: 'Parrot', wordZh: '鹦鹉', emoji: '🦜' },
  { id: 'q', letter: 'Q', nameZh: 'kiu', nameEn: 'Q', word: 'Queen', wordZh: '女王', emoji: '👸' },
  { id: 'r', letter: 'R', nameZh: 'a', nameEn: 'R', word: 'Rainbow', wordZh: '彩虹', emoji: '🌈' },
  { id: 's', letter: 'S', nameZh: 'ai', nameEn: 'S', word: 'Sun', wordZh: '太阳', emoji: '☀️' },
  { id: 't', letter: 'T', nameZh: 'ti', nameEn: 'T', word: 'Tree', wordZh: '树', emoji: '🌳' },
  { id: 'u', letter: 'U', nameZh: 'you', nameEn: 'U', word: 'Umbrella', wordZh: '雨伞', emoji: '☂️' },
  { id: 'v', letter: 'V', nameZh: 'wei', nameEn: 'V', word: 'Violin', wordZh: '小提琴', emoji: '🎻' },
  { id: 'w', letter: 'W', nameZh: 'dabu', nameEn: 'W', word: 'Water', wordZh: '水', emoji: '💧' },
  { id: 'x', letter: 'X', nameZh: 'ai', nameEn: 'X', word: 'Xylophone', wordZh: '木琴', emoji: '🎵' },
  { id: 'y', letter: 'Y', nameZh: 'wai', nameEn: 'Y', word: 'Yak', wordZh: '牦牛', emoji: '🦬' },
  { id: 'z', letter: 'Z', nameZh: 'zi', nameEn: 'Z', word: 'Zebra', wordZh: '斑马', emoji: '🦓' },
];

// 单词数据
export const wordsData: WordItem[] = [
  // 动物
  { id: 'w1', word: 'Cat', translation: '猫', emoji: '🐱', category: 'animal' },
  { id: 'w2', word: 'Dog', translation: '狗', emoji: '🐕', category: 'animal' },
  { id: 'w3', word: 'Bird', translation: '鸟', emoji: '🐦', category: 'animal' },
  { id: 'w4', word: 'Fish', translation: '鱼', emoji: '🐟', category: 'animal' },
  { id: 'w5', word: 'Rabbit', translation: '兔子', emoji: '🐰', category: 'animal' },
  { id: 'w6', word: 'Bear', translation: '熊', emoji: '🐻', category: 'animal' },
  { id: 'w7', word: 'Elephant', translation: '大象', emoji: '🐘', category: 'animal' },
  { id: 'w8', word: 'Monkey', translation: '猴子', emoji: '🐵', category: 'animal' },
  // 食物
  { id: 'w9', word: 'Apple', translation: '苹果', emoji: '🍎', category: 'food' },
  { id: 'w10', word: 'Banana', translation: '香蕉', emoji: '🍌', category: 'food' },
  { id: 'w11', word: 'Orange', translation: '橙子', emoji: '🍊', category: 'food' },
  { id: 'w12', word: 'Bread', translation: '面包', emoji: '🍞', category: 'food' },
  { id: 'w13', word: 'Milk', translation: '牛奶', emoji: '🥛', category: 'food' },
  { id: 'w14', word: 'Egg', translation: '鸡蛋', emoji: '🥚', category: 'food' },
  { id: 'w15', word: 'Cake', translation: '蛋糕', emoji: '🎂', category: 'food' },
  { id: 'w16', word: 'Pizza', translation: '披萨', emoji: '🍕', category: 'food' },
  // 颜色
  { id: 'w17', word: 'Red', translation: '红色', emoji: '🔴', category: 'color' },
  { id: 'w18', word: 'Blue', translation: '蓝色', emoji: '🔵', category: 'color' },
  { id: 'w19', word: 'Green', translation: '绿色', emoji: '🟢', category: 'color' },
  { id: 'w20', word: 'Yellow', translation: '黄色', emoji: '🟡', category: 'color' },
  // 自然
  { id: 'w21', word: 'Sun', translation: '太阳', emoji: '☀️', category: 'nature' },
  { id: 'w22', word: 'Moon', translation: '月亮', emoji: '🌙', category: 'nature' },
  { id: 'w23', word: 'Star', translation: '星星', emoji: '⭐', category: 'nature' },
  { id: 'w24', word: 'Rain', translation: '雨', emoji: '🌧️', category: 'nature' },
  { id: 'w25', word: 'Flower', translation: '花', emoji: '🌸', category: 'nature' },
  { id: 'w26', word: 'Tree', translation: '树', emoji: '🌳', category: 'nature' },
  // 物品
  { id: 'w27', word: 'Book', translation: '书', emoji: '📚', category: 'object' },
  { id: 'w28', word: 'Ball', translation: '球', emoji: '⚽', category: 'object' },
  { id: 'w29', word: 'Car', translation: '汽车', emoji: '🚗', category: 'object' },
  { id: 'w30', word: 'Chair', translation: '椅子', emoji: '🪑', category: 'object' },
  // 动作
  { id: 'w31', word: 'Run', translation: '跑', emoji: '🏃', category: 'action' },
  { id: 'w32', word: 'Jump', translation: '跳', emoji: '🦘', category: 'action' },
  { id: 'w33', word: 'Swim', translation: '游泳', emoji: '🏊', category: 'action' },
  { id: 'w34', word: 'Sing', translation: '唱歌', emoji: '🎤', category: 'action' },
  { id: 'w35', word: 'Dance', translation: '跳舞', emoji: '💃', category: 'action' },
  { id: 'w36', word: 'Eat', translation: '吃', emoji: '🍽️', category: 'action' },
];

// 导出所有数据
export const eduData = {
  colors: colorsData,
  shapes: shapesData,
  numbers: numbersData,
  letters: lettersData,
  words: wordsData,
};
