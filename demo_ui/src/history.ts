// 사용자 요청 2026-10-23 : 링크 이동을 옵시디언처럼 ( 같은 탭 이동 · Ctrl+클릭 새 탭 · 뒤로 / 앞으로 · 미리보기 ). 링크는 에이전트가 만든 것만 그린다 - 본문 글자에 링크를 새로 걸지 않는다 ( 지침 3절 20 )
// 활성 탭 키의 방문 기록 - 순수 함수
export type History = { stack: string[]; index: number }

export const HISTORY_MAX = 100
export const EMPTY_HISTORY: History = { stack: [], index: -1 }

// 같은 키가 이어지면 그대로이고, 뒤로 간 뒤에 쌓으면 앞쪽 기록은 버린다
export function push(history: History, key: string): History {
  if (history.stack[history.index] === key) return history
  const stack = [...history.stack.slice(0, history.index + 1), key].slice(-HISTORY_MAX)
  return { stack, index: stack.length - 1 }
}

export function canBack(history: History): boolean {
  return history.index > 0
}

export function canForward(history: History): boolean {
  return history.index < history.stack.length - 1
}

export function back(history: History): History {
  return canBack(history) ? { ...history, index: history.index - 1 } : history
}

export function forward(history: History): History {
  return canForward(history) ? { ...history, index: history.index + 1 } : history
}

// 쓸 수 없는 항목은 건너뛰고 다음 유효한 곳으로 - 없으면 그대로
export function backValid(history: History, isValid: (key: string) => boolean): History {
  for (let index = history.index - 1; index >= 0; index -= 1) {
    if (isValid(history.stack[index])) return { ...history, index }
  }
  return history
}

export function forwardValid(history: History, isValid: (key: string) => boolean): History {
  for (let index = history.index + 1; index < history.stack.length; index += 1) {
    if (isValid(history.stack[index])) return { ...history, index }
  }
  return history
}
