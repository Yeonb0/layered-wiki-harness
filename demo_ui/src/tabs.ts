// 사용자 결정 2026-10-23 : 가운데 탭 상태 - 대시보드 · 그래프는 고정 탭, 노트 탭은 여러 개 열고 닫는다
export const DASHBOARD_TAB = 'dashboard'
export const GRAPH_TAB = 'graph'
const FIXED_TABS = [DASHBOARD_TAB, GRAPH_TAB]

export type TabState = { tabs: string[]; active: string }

export const INITIAL_TABS: TabState = { tabs: [...FIXED_TABS], active: DASHBOARD_TAB }

export function noteTabKey(noteId: string): string {
  return `note:${noteId}`
}

export function noteIdOfTab(key: string): string | null {
  return key.startsWith('note:') ? key.slice('note:'.length) : null
}

// 없는 탭은 활성으로 만들지 않는다
export function activate(state: TabState, key: string): TabState {
  return state.tabs.includes(key) ? { ...state, active: key } : state
}

// 같은 노트를 두 번 열면 탭이 늘지 않고 그 탭이 활성이 된다
export function openTab(state: TabState, noteId: string): TabState {
  const key = noteTabKey(noteId)
  return state.tabs.includes(key) ? { ...state, active: key } : { tabs: [...state.tabs, key], active: key }
}

// 고정 탭은 닫지 않는다, 활성 탭을 닫으면 왼쪽 옆 탭 ( 없으면 오른쪽 ) 이 활성이 된다
export function closeTab(state: TabState, key: string): TabState {
  if (FIXED_TABS.includes(key)) return state
  const index = state.tabs.indexOf(key)
  if (index < 0) return state
  const tabs = state.tabs.filter((tab) => tab !== key)
  if (state.active !== key) return { tabs, active: state.active }
  return { tabs, active: tabs[Math.max(0, index - 1)] }
}

// 모드를 바꿔 보기가 달라지면 새 보기에 없는 노트의 탭을 닫는다 - 활성 탭이 닫히면 대시보드로 돌아간다
export function syncTabs(state: TabState, noteIds: Set<string>): TabState {
  const tabs = state.tabs.filter((tab) => {
    const noteId = noteIdOfTab(tab)
    return noteId === null || noteIds.has(noteId)
  })
  if (tabs.length === state.tabs.length) return state
  return { tabs, active: tabs.includes(state.active) ? state.active : DASHBOARD_TAB }
}
