import { describe, expect, it } from 'vitest'
import {
  activate, closeTab, COMPARE_MODE_TAB, COMPARE_VIEWER_TAB, DASHBOARD_TAB, GRAPH_TAB, INITIAL_TABS, LIVE_TAB, MEETINGS_TAB, meetingIdOfTab, meetingTabKey, noteTabKey, openMeetingTab, openTab,
  navigateTo, syncTabs, wantsNewTab,
} from './tabs'

const FIXED = [DASHBOARD_TAB, GRAPH_TAB, MEETINGS_TAB, COMPARE_VIEWER_TAB, COMPARE_MODE_TAB, LIVE_TAB]

describe('탭 상태', () => {
  it('처음에는 고정 탭 여섯 ( 대시보드, 그래프, 회의, 보는 사람 비교, 모드 비교, 라이브 투입 ) 이고 대시보드가 활성이다', () => {
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

describe('회의 탭', () => {
  it('키를 만들고 되돌린다', () => {
    expect(meetingTabKey('m0001')).toBe('meeting:m0001')
    expect(meetingIdOfTab('meeting:m0001')).toBe('m0001')
    expect(meetingIdOfTab('note:m0001')).toBeNull()
  })

  it('같은 회의를 두 번 열어도 탭이 늘지 않고 닫을 수 있다', () => {
    const once = openMeetingTab(INITIAL_TABS, 'm0001')
    expect(openMeetingTab(activate(once, DASHBOARD_TAB), 'm0001').tabs).toEqual(once.tabs)
    expect(closeTab(once, meetingTabKey('m0001')).tabs).toEqual(FIXED)
  })

  it('노트 보기가 바뀌어도 회의 탭은 남는다', () => {
    const once = openMeetingTab(INITIAL_TABS, 'm0001')
    expect(syncTabs(once, new Set()).tabs).toContain(meetingTabKey('m0001'))
  })
})

describe('navigateTo', () => {
  const open = (...ids: string[]) => ids.reduce((state, id) => openTab(state, id), INITIAL_TABS)

  it('이미 열린 탭이면 그 탭이 활성이 되고 탭은 늘지 않는다', () => {
    const state = activate(open('노트1', '노트2'), noteTabKey('노트1'))
    const next = navigateTo(state, '노트2', { newTab: false })
    expect(next.tabs).toEqual(state.tabs)
    expect(next.active).toBe(noteTabKey('노트2'))
  })

  it('활성 노트 탭에서는 그 자리를 대상 노트 탭으로 바꾼다 ( 순서 유지 )', () => {
    const state = activate(open('노트1', '노트2', '노트3'), noteTabKey('노트2'))
    const next = navigateTo(state, '노트4', { newTab: false })
    expect(next.tabs).toEqual([...FIXED, noteTabKey('노트1'), noteTabKey('노트4'), noteTabKey('노트3')])
    expect(next.active).toBe(noteTabKey('노트4'))
  })

  it('고정 탭이 활성이면 새 탭을 연다', () => {
    const next = navigateTo(INITIAL_TABS, '노트1', { newTab: false })
    expect(next.tabs).toEqual([...FIXED, noteTabKey('노트1')])
    expect(next.active).toBe(noteTabKey('노트1'))
  })

  it('newTab 이면 활성 노트 탭이 있어도 새 탭을 연다', () => {
    const state = open('노트1')
    const next = navigateTo(state, '노트2', { newTab: true })
    expect(next.tabs).toEqual([...FIXED, noteTabKey('노트1'), noteTabKey('노트2')])
    expect(next.active).toBe(noteTabKey('노트2'))
  })

  it('회의 탭이 활성이면 새 탭을 연다 ( 회의 탭은 바꾸지 않는다 )', () => {
    const state = openMeetingTab(INITIAL_TABS, 'm0001')
    const next = navigateTo(state, '노트1', { newTab: false })
    expect(next.tabs).toEqual([...FIXED, meetingTabKey('m0001'), noteTabKey('노트1')])
    expect(next.active).toBe(noteTabKey('노트1'))
  })
})

describe('wantsNewTab', () => {
  it('Ctrl · Cmd · 가운데 버튼이면 새 탭이다', () => {
    expect(wantsNewTab({ ctrlKey: true })).toBe(true)
    expect(wantsNewTab({ metaKey: true })).toBe(true)
    expect(wantsNewTab({ button: 1 })).toBe(true)
    expect(wantsNewTab({ button: 0 })).toBe(false)
    expect(wantsNewTab(undefined)).toBe(false)
  })
})
