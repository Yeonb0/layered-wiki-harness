// 사용자 결정 2026-10-23 : 가운데 탭 상태 - 대시보드 · 그래프는 고정 탭, 노트 탭은 여러 개 열고 닫는다
export const DASHBOARD_TAB = 'dashboard'
export const GRAPH_TAB = 'graph'
export const MEETINGS_TAB = 'meetings'
export const COMPARE_VIEWER_TAB = 'compare-viewer'
export const COMPARE_MODE_TAB = 'compare-mode'
export const LIVE_TAB = 'live'
// 고정 탭 순서 : 대시보드, 그래프, 회의, 보는 사람 비교, 모드 비교, 라이브 투입
const FIXED_TABS = [DASHBOARD_TAB, GRAPH_TAB, MEETINGS_TAB, COMPARE_VIEWER_TAB, COMPARE_MODE_TAB, LIVE_TAB]

export type TabState = { tabs: string[]; active: string }

export const INITIAL_TABS: TabState = { tabs: [...FIXED_TABS], active: DASHBOARD_TAB }

export function noteTabKey(noteId: string): string {
  return `note:${noteId}`
}

export function noteIdOfTab(key: string): string | null {
  return key.startsWith('note:') ? key.slice('note:'.length) : null
}

export function meetingTabKey(meetingId: string): string {
  return `meeting:${meetingId}`
}

export function meetingIdOfTab(key: string): string | null {
  return key.startsWith('meeting:') ? key.slice('meeting:'.length) : null
}

// 같은 회의를 두 번 열면 탭이 늘지 않고 그 탭이 활성이 된다
export function openMeetingTab(state: TabState, meetingId: string): TabState {
  const key = meetingTabKey(meetingId)
  return state.tabs.includes(key) ? { ...state, active: key } : { tabs: [...state.tabs, key], active: key }
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

// 사용자 요청 2026-10-23 : 링크 이동을 옵시디언처럼 ( 같은 탭 이동 · Ctrl+클릭 새 탭 · 뒤로 / 앞으로 · 미리보기 ). 링크는 에이전트가 만든 것만 그린다 - 본문 글자에 링크를 새로 걸지 않는다 ( 지침 3절 20 )
// 노트를 여는 클릭 이벤트의 필요한 부분만 - Ctrl · Cmd · 가운데 버튼이면 새 탭이다
export type OpenEvent = { ctrlKey?: boolean; metaKey?: boolean; button?: number }

export function wantsNewTab(ev?: OpenEvent): boolean {
  return !!ev && (!!ev.ctrlKey || !!ev.metaKey || ev.button === 1)
}

// 이미 열린 탭이면 그 탭이 활성이 된다. 아니면 새 탭을 강제했거나 활성 탭이 노트 탭이 아닐 때 새 탭을 열고, 활성 노트 탭이면 그 자리를 대상 노트 탭으로 바꾼다 ( 순서 유지 )
export function navigateTo(state: TabState, noteId: string, opts: { newTab: boolean }): TabState {
  const key = noteTabKey(noteId)
  if (state.tabs.includes(key)) return { ...state, active: key }
  if (opts.newTab || noteIdOfTab(state.active) === null) return openTab(state, noteId)
  return { tabs: state.tabs.map((tab) => (tab === state.active ? key : tab)), active: key }
}
