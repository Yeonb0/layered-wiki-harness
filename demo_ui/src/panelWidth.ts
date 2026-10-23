// 사용자 요청 2026-10-23 : 탐색기 · 연결 패널 폭을 끌어서 바꾼다. 폭은 이 브라우저에만 기억한다 ( 화면 편의, 보기 데이터와 무관 )
export const PANEL_LIMITS = {
  sidebar: { min: 200, max: 520, initial: 270 },
  connections: { min: 220, max: 560, initial: 300 },
} as const

export type Panel = keyof typeof PANEL_LIMITS
export type Widths = Record<Panel, number>

export const STORAGE_KEY = 'layered-wiki-demo:panel-widths'

const PANELS = Object.keys(PANEL_LIMITS) as Panel[]

// 정수로 반올림하고 min · max 안으로 맞춘다 - 숫자가 아니면 initial
export function clampWidth(panel: Panel, px: number): number {
  const limits = PANEL_LIMITS[panel]
  if (!Number.isFinite(px)) return limits.initial
  return Math.min(limits.max, Math.max(limits.min, Math.round(px)))
}

export function initialWidths(): Widths {
  return { sidebar: PANEL_LIMITS.sidebar.initial, connections: PANEL_LIMITS.connections.initial }
}

function widthsFromObject(parsed: Record<string, unknown>): Widths {
  const widths = initialWidths()
  for (const panel of PANELS) {
    const value = parsed[panel]
    if (typeof value === 'number') widths[panel] = clampWidth(panel, value)
  }
  return widths
}

function asObject(raw: string | null): Record<string, unknown> | null {
  if (raw === null) return null
  let parsed: unknown
  try {
    parsed = JSON.parse(raw)
  } catch {
    return null
  }
  return typeof parsed === 'object' && parsed !== null ? (parsed as Record<string, unknown>) : null
}

// JSON 이 아니거나 키가 없거나 숫자가 아니면 그 칸만 initial, 숫자면 범위 안으로 맞춘다
export function parseWidths(raw: string | null): Widths {
  const parsed = asObject(raw)
  return parsed === null ? initialWidths() : widthsFromObject(parsed)
}

// 사용자 요청 2026-10-23 : 탐색기 · 연결 패널은 폭 조절에 더해 접기도 된다. 화면 편의 값이며 보기 데이터와 무관
export type PanelState = { widths: Widths; collapsed: Record<Panel, boolean> }

// 폭을 min 보다 이만큼 더 줄이려 끌면 접는다
export const COLLAPSE_SNAP = 60

export function shouldCollapse(panel: Panel, rawPx: number): boolean {
  return rawPx < PANEL_LIMITS[panel].min - COLLAPSE_SNAP
}

export function initialPanelState(): PanelState {
  return { widths: initialWidths(), collapsed: { sidebar: false, connections: false } }
}

// 새 형식 { widths, collapsed } 과 예전 형식 ( 폭만 든 객체 ) 을 모두 읽는다 - 예전 형식이면 접힘은 모두 false, boolean 이 아닌 접힘 값도 false
export function parsePanelState(raw: string | null): PanelState {
  const parsed = asObject(raw)
  if (parsed === null) return initialPanelState()
  const widthsObject = parsed.widths
  const isNew = typeof widthsObject === 'object' && widthsObject !== null
  const state = initialPanelState()
  state.widths = widthsFromObject(isNew ? (widthsObject as Record<string, unknown>) : parsed)
  const collapsedObject = isNew && typeof parsed.collapsed === 'object' && parsed.collapsed !== null ? (parsed.collapsed as Record<string, unknown>) : {}
  for (const panel of PANELS) {
    state.collapsed[panel] = collapsedObject[panel] === true
  }
  return state
}

// 저장소 접근이 막혀도 ( 사생활 보호 모드 등 ) 화면은 쓸 수 있어야 하고, 이 값은 화면 편의일 뿐 보기 결과와 무관해서 조용히 initial 로 돌아가는 것이 맞다
export function loadPanelState(): PanelState {
  try {
    return parsePanelState(window.localStorage.getItem(STORAGE_KEY))
  } catch {
    return initialPanelState()
  }
}

export function savePanelState(state: PanelState): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(state))
  } catch {
    // 저장하지 못해도 이번 화면의 폭 · 접힘은 그대로 쓴다 ( 화면 편의 값이라 보기 결과와 무관 )
  }
}
