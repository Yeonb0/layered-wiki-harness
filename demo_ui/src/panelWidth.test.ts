import { describe, expect, it } from 'vitest'
import { clampWidth, COLLAPSE_SNAP, parsePanelState, parseWidths, PANEL_LIMITS, shouldCollapse, type PanelState } from './panelWidth'

describe('clampWidth', () => {
  it('min 아래는 min, max 위는 max 로 맞춘다', () => {
    expect(clampWidth('sidebar', 0)).toBe(PANEL_LIMITS.sidebar.min)
    expect(clampWidth('sidebar', 99999)).toBe(PANEL_LIMITS.sidebar.max)
    expect(clampWidth('connections', -50)).toBe(PANEL_LIMITS.connections.min)
    expect(clampWidth('connections', 99999)).toBe(PANEL_LIMITS.connections.max)
  })

  it('경계값은 그대로 둔다', () => {
    expect(clampWidth('sidebar', 200)).toBe(200)
    expect(clampWidth('sidebar', 520)).toBe(520)
  })

  it('정수로 반올림한다', () => {
    expect(clampWidth('sidebar', 300.4)).toBe(300)
    expect(clampWidth('sidebar', 300.5)).toBe(301)
  })

  it('NaN 과 무한대는 initial 이다', () => {
    expect(clampWidth('sidebar', NaN)).toBe(PANEL_LIMITS.sidebar.initial)
    expect(clampWidth('connections', Infinity)).toBe(PANEL_LIMITS.connections.initial)
  })
})

describe('parseWidths', () => {
  const initial = { sidebar: PANEL_LIMITS.sidebar.initial, connections: PANEL_LIMITS.connections.initial }

  it('null 이면 initial 이다', () => {
    expect(parseWidths(null)).toEqual(initial)
  })

  it('깨진 JSON 이거나 객체가 아니면 initial 이다', () => {
    expect(parseWidths('{깨짐')).toEqual(initial)
    expect(parseWidths('123')).toEqual(initial)
    expect(parseWidths('null')).toEqual(initial)
  })

  it('일부 키만 있으면 그 칸만 읽고 나머지는 initial 이다', () => {
    expect(parseWidths('{"sidebar": 333}')).toEqual({ sidebar: 333, connections: initial.connections })
    expect(parseWidths('{"connections": 400}')).toEqual({ sidebar: initial.sidebar, connections: 400 })
  })

  it('숫자가 아닌 값은 그 칸만 initial 이다', () => {
    expect(parseWidths('{"sidebar": "넓게", "connections": 350}')).toEqual({ sidebar: initial.sidebar, connections: 350 })
  })

  it('범위 밖 숫자는 범위 안으로 맞춘다', () => {
    expect(parseWidths('{"sidebar": 10, "connections": 9999}')).toEqual({
      sidebar: PANEL_LIMITS.sidebar.min,
      connections: PANEL_LIMITS.connections.max,
    })
  })
})

describe('shouldCollapse', () => {
  it('min 에서 COLLAPSE_SNAP 만큼 아래로 내려가야 접힌다 ( 경계 포함하지 않음 )', () => {
    const min = PANEL_LIMITS.sidebar.min
    expect(shouldCollapse('sidebar', min - COLLAPSE_SNAP)).toBe(false)
    expect(shouldCollapse('sidebar', min - COLLAPSE_SNAP - 1)).toBe(true)
    expect(shouldCollapse('sidebar', min)).toBe(false)
    expect(shouldCollapse('connections', PANEL_LIMITS.connections.min - COLLAPSE_SNAP - 1)).toBe(true)
  })

  it('넓은 값은 접지 않는다', () => {
    expect(shouldCollapse('sidebar', 5000)).toBe(false)
  })
})

describe('parsePanelState', () => {
  const initialWidths = { sidebar: PANEL_LIMITS.sidebar.initial, connections: PANEL_LIMITS.connections.initial }
  const open = { sidebar: false, connections: false }

  it('null · 깨진 JSON 이면 초기 상태이고 접힘은 모두 false 다', () => {
    expect(parsePanelState(null)).toEqual({ widths: initialWidths, collapsed: open })
    expect(parsePanelState('{깨짐')).toEqual({ widths: initialWidths, collapsed: open })
  })

  it('예전 형식 ( 폭만 든 객체 ) 을 읽고 접힘은 모두 false 다', () => {
    expect(parsePanelState('{"sidebar": 333, "connections": 410}')).toEqual({ widths: { sidebar: 333, connections: 410 }, collapsed: open })
  })

  it('새 형식은 저장한 그대로 왕복한다', () => {
    const state: PanelState = { widths: { sidebar: 300, connections: 350 }, collapsed: { sidebar: true, connections: false } }
    expect(parsePanelState(JSON.stringify(state))).toEqual(state)
  })

  it('새 형식에서도 범위 밖 폭은 범위 안으로 맞춘다', () => {
    const raw = JSON.stringify({ widths: { sidebar: 1, connections: 99999 }, collapsed: {} })
    expect(parsePanelState(raw).widths).toEqual({ sidebar: PANEL_LIMITS.sidebar.min, connections: PANEL_LIMITS.connections.max })
  })

  it('collapsed 가 boolean 이 아니면 그 칸은 false 다', () => {
    const raw = JSON.stringify({ widths: {}, collapsed: { sidebar: 'true', connections: 1 } })
    expect(parsePanelState(raw).collapsed).toEqual(open)
    expect(parsePanelState(JSON.stringify({ widths: {}, collapsed: 'yes' })).collapsed).toEqual(open)
    expect(parsePanelState(JSON.stringify({ widths: {} })).collapsed).toEqual(open)
  })
})
