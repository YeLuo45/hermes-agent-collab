import { useState, useCallback, useEffect } from 'react';

// 动画状态
export interface AnimationState {
  isPlaying: boolean;
  isCorrect: boolean | null;
  feedback: 'success' | 'error' | 'idle';
}

// 通用动画hook
export function useAnimation() {
  const [state, setState] = useState<AnimationState>({
    isPlaying: false,
    isCorrect: null,
    feedback: 'idle',
  });

  const playSuccess = useCallback(() => {
    setState({ isPlaying: true, isCorrect: true, feedback: 'success' });
    setTimeout(() => {
      setState({ isPlaying: false, isCorrect: true, feedback: 'success' });
    }, 300);
    setTimeout(() => {
      setState({ isPlaying: false, isCorrect: null, feedback: 'idle' });
    }, 800);
  }, []);

  const playError = useCallback(() => {
    setState({ isPlaying: true, isCorrect: false, feedback: 'error' });
    setTimeout(() => {
      setState({ isPlaying: false, isCorrect: false, feedback: 'error' });
    }, 300);
    setTimeout(() => {
      setState({ isPlaying: false, isCorrect: null, feedback: 'idle' });
    }, 600);
  }, []);

  const reset = useCallback(() => {
    setState({ isPlaying: false, isCorrect: null, feedback: 'idle' });
  }, []);

  return { state, playSuccess, playError, reset };
}

// 闪烁效果hook
export function useBounce(index: number, delay: number = 0) {
  const [isBouncing, setIsBouncing] = useState(false);

  useEffect(() => {
    const timer = setTimeout(() => {
      setIsBouncing(true);
      setTimeout(() => setIsBouncing(false), 500);
    }, delay + index * 100);
    return () => clearTimeout(timer);
  }, [index, delay]);

  return isBouncing;
}

// 打字机效果hook
export function useTypewriter(text: string, speed: number = 50) {
  const [displayText, setDisplayText] = useState('');
  const [isComplete, setIsComplete] = useState(false);

  useEffect(() => {
    setDisplayText('');
    setIsComplete(false);
    let i = 0;
    const timer = setInterval(() => {
      if (i < text.length) {
        setDisplayText(text.slice(0, i + 1));
        i++;
      } else {
        setIsComplete(true);
        clearInterval(timer);
      }
    }, speed);
    return () => clearInterval(timer);
  }, [text, speed]);

  return { displayText, isComplete };
}
