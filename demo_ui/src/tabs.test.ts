import { describe, expect, it } from 'vitest'
import {
  activate, closeTab, COMPARE_MODE_TAB, COMPARE_VIEWER_TAB, DASHBOARD_TAB, GRAPH_TAB, INITIAL_TABS, LIVE_TAB, noteTabKey, openTab,
  syncTabs,
} from './tabs'

const FIXED = [DASHBOARD_TAB, GRAPH_TAB, COMPARE_VIEWER_TAB, COMPARE_MODE_TAB, LIVE_TAB]

describe('탭 상태', () => {
  it('처음에는 고정 탭 다섯 ( 대시보드, 그래프, 보는 사람 비교, 모드 비교, 라이브 투입 ) 이고 대시보드가 활성이다', () => {
    expect(INITIAL_TABS).toEqual({ tabs: FIXED, active: DASHBOARD_TAB })
  })

  it('openTab : 노트 탭을 추가하고 활성으로 만든다', () => {
    const state = openTab(INITIAL_TABS, '노트1')
    expect(state.tabs).toEqual([...FIXED, noteTabKey('노트1')])
    expect(state.active).toBe(noteTabKey('노트1'))
  })

  it('같은 노트를 두 번 열면 탭이 늘지 않고 그 탭이 활성이 된다', () => {
    const once = openTab(openTab(INITIAL_TABS, '노트1'), '노트2')
    const again = openTab(activate(once, DASHBOARD_TAB), '노트1')
    expect(again.tabs).toEqual(once.tabs)
    expect(again.active).toBe(noteTabKey('노트1'))
  })

  it('closeTab : 활성 탭을 닫으면 왼쪽 옆 탭이 활성이 된다', () => {
    const state = openTab(openTab(INITIAL_TABS, '노트1'), '노트2')
    const closed = closeTab(state, noteTabKey('노트2'))
    expect(closed.tabs).toEqual([...FIXED, noteTabKey('노트1')])
    expect(closed.active).toBe(noteTabKey('노트1'))
    expect(closeTab(closed, noteTabKey('노트1')).active).toBe(LIVE_TAB)
  })

  it('closeTab : 활성이 아닌 탭을 닫으면 활성은 그대로다', () => {
    const state = openTab(openTab(INITIAL_TABS, '노트1'), '노트2')
    const closed = closeTab(state, noteTabKey('노트1'))
    expect(closed.active).toBe(noteTabKey('노트2'))
    expect(closed.tabs).not.toContain(noteTabKey('노트1'))
  })

  it('closeTab : 고정 탭과 없는 탭은 닫지 않는다', () => {
    const state = openTab(INITIAL_TABS, '노트1')
    for (const key of FIXED) {
      expect(closeTab(state, key)).toEqual(state)
    }
    expect(closeTab(state, noteTabKey('없는노트'))).toEqual(state)
  })

  it('activate : 없는 탭은 활성으로 만들지 않는다', () => {
    expect(activate(INITIAL_TABS, GRAPH_TAB).active).toBe(GRAPH_TAB)
    expect(activate(INITIAL_TABS, noteTabKey('없는노트'))).toEqual(INITIAL_TABS)
  })

  it('syncTabs : 새 보기에 없는 노트의 탭을 닫고 활성이 닫히면 대시보드로 돌아간다', () => {
    const state = openTab(openTab(INITIAL_TABS, '노트1'), '노트2')
    const synced = syncTabs(state, new Set(['노트1']))
    expect(synced.tabs).toEqual([...FIXED, noteTabKey('노트1')])
    expect(synced.active).toBe(DASHBOARD_TAB)
    expect(syncTabs(state, new Set(['노트1', '노트2']))).toBe(state)
  })
})
