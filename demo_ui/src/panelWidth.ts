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

// JSON 이 아니거나 키가 없거나 숫자가 아니면 그 칸만 initial, 숫자면 범위 안으로 맞춘다
export function parseWidths(raw: string | null): Widths {
  const widths = initialWidths()
  if (raw === null) return widths
  let parsed: unknown
  try {
    parsed = JSON.parse(raw)
  } catch {
    return widths
  }
  if (typeof parsed !== 'object' || parsed === null) return widths
  for (const panel of PANELS) {
    const value = (parsed as Record<string, unknown>)[panel]
    if (typeof value === 'number') widths[panel] = clampWidth(panel, value)
  }
  return widths
}

// 저장소 접근이 막혀도 ( 사생활 보호 모드 등 ) 화면은 쓸 수 있어야 하고, 이 값은 화면 편의일 뿐 보기 결과와 무관해서 조용히 initial 로 돌아가는 것이 맞다
export function loadWidths(): Widths {
  try {
    return parseWidths(window.localStorage.getItem(STORAGE_KEY))
  } catch {
    return initialWidths()
  }
}

export function saveWidths(widths: Widths): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(widths))
  } catch {
    // 저장하지 못해도 이번 화면의 폭은 그대로 쓴다 ( 화면 편의 값이라 보기 결과와 무관 )
  }
}
