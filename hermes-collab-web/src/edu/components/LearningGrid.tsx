import type { EduModule } from '../types';
import {
  ColorCard,
  ShapeCard,
  NumberCard,
  LetterCard,
  WordCard,
} from './LearningCards';
import type { ColorItem, ShapeItem, NumberItem, LetterItem, WordItem } from '../types';

interface LearningGridProps {
  module: EduModule;
  data: ColorItem[] | ShapeItem[] | NumberItem[] | LetterItem[] | WordItem[];
  selectedId?: string;
  onSelectItem?: (id: string) => void;
}

export function LearningGrid({ module, data, selectedId, onSelectItem }: LearningGridProps) {
  const renderItem = (item: any) => {
    const isSelected = item.id === selectedId;
    const handleClick = () => onSelectItem?.(item.id);

    switch (module) {
      case 'colors':
        return (
          <ColorCard
            key={item.id}
            item={item as ColorItem}
            onClick={handleClick}
            isSelected={isSelected}
          />
        );
      case 'shapes':
        return (
          <ShapeCard
            key={item.id}
            item={item as ShapeItem}
            onClick={handleClick}
            isSelected={isSelected}
          />
        );
      case 'numbers':
        return (
          <NumberCard
            key={item.id}
            item={item as NumberItem}
            onClick={handleClick}
            isSelected={isSelected}
          />
        );
      case 'letters':
        return (
          <LetterCard
            key={item.id}
            item={item as LetterItem}
            onClick={handleClick}
            isSelected={isSelected}
          />
        );
      case 'words':
        return (
          <WordCard
            key={item.id}
            item={item as WordItem}
            onClick={handleClick}
            isSelected={isSelected}
          />
        );
      default:
        return null;
    }
  };

  return (
    <div className="flex flex-wrap justify-center gap-6 p-6">
      {data.map((item, index) => (
        <div
          key={item.id}
          className="animate-fadeIn"
          style={{ animationDelay: `${index * 50}ms` }}
        >
          {renderItem(item)}
        </div>
      ))}
    </div>
  );
}
