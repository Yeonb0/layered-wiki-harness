import { describe, expect, it } from 'vitest'
import { clampWidth, parseWidths, PANEL_LIMITS } from './panelWidth'

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
