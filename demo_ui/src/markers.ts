// 사용자 결정 2026-10-23 : 누출 표지는 합성 코퍼스 README 의 표와 같은 목록을 쓴다 - 메커니즘 시연이며 측정 결과가 아니다
import type { ViewNote } from './api'

export type Marker = { text: string; homeLayer: '개인' | '팀' | '전사'; homeGroup: string }

export const MARKERS: Marker[] = [
  { text: '붉은 매듭', homeLayer: '팀', homeGroup: '팀1' },
  { text: '황금비늘', homeLayer: '팀', homeGroup: '팀2' },
  { text: '17%', homeLayer: '팀', homeGroup: '팀2' },
  { text: 'sandbox-7', homeLayer: '개인', homeGroup: '팀원A' },
  { text: '133ms', homeLayer: '개인', homeGroup: '팀원A' },
  { text: '0.8%p', homeLayer: '개인', homeGroup: '팀원B' },
  { text: '1 : 0.37', homeLayer: '개인', homeGroup: '팀원C' },
  { text: '2.6점', homeLayer: '개인', homeGroup: '팀원D' },
]

// up : 노트 층이 표지 층보다 위 ( 누출 ), cross : 같은 층 다른 그룹 ( 누출 정의 밖 ), home : 제자리, down : 아래 층
export type MarkerKind = 'up' | 'cross' | 'home' | 'down'

export const MARKER_KIND_LABEL: Record<MarkerKind, string> = {
  up: '층 위로 ( 누출 )',
  cross: '같은 층 다른 그룹',
  home: '제자리',
  down: '아래 층',
}

// 층 순서 : 개인 < 팀 < 전사
const RANK: Record<string, number> = { 개인: 0, 팀: 1, 전사: 2 }

export function classifyMarker(note: { layer: string; group_label: string | null }, marker: Marker): MarkerKind {
  const noteRank = RANK[note.layer]
  // 층 순서에 없는 값은 위인지 아래인지 알 수 없다 - 조용히 넘기지 않는다
  if (noteRank === undefined) throw new Error(`알 수 없는 층 : ${note.layer}`)
  const markerRank = RANK[marker.homeLayer]
  if (noteRank > markerRank) return 'up'
  if (noteRank < markerRank) return 'down'
  return note.group_label === marker.homeGroup ? 'home' : 'cross'
}

// 제목 + 본문에서 표지 문자열을 정확히 일치로 센다 - 정규식 · 대소문자 무시 · 공백 정규화를 쓰지 않는다
export function findMarkers(note: ViewNote): { marker: Marker; kind: MarkerKind; count: number }[] {
  const text = `${note.title}\n${note.body}`
  const out: { marker: Marker; kind: MarkerKind; count: number }[] = []
  for (const marker of MARKERS) {
    const count = text.split(marker.text).length - 1
    if (count > 0) out.push({ marker, kind: classifyMarker(note, marker), count })
  }
  return out
}

// 본문 강조용 조각 나누기 - 겹치는 표지는 MARKERS 순서상 앞의 것이 이긴다 ( 뒤의 표지는 이미 차지한 구간을 건드리지 못한다 )
// markers 는 겹침 규칙을 시험하려고 바꿀 수 있게 열어 둔 인자이고 화면은 기본값 ( MARKERS ) 만 쓴다
export function splitByMarkers(text: string, markers: Marker[] = MARKERS): { text: string; marker: Marker | null }[] {
  const claimed: { start: number; end: number; marker: Marker }[] = []
  for (const marker of markers) {
    let from = 0
    for (;;) {
      const start = text.indexOf(marker.text, from)
      if (start < 0) break
      const end = start + marker.text.length
      if (!claimed.some((range) => start < range.end && range.start < end)) claimed.push({ start, end, marker })
      from = end
    }
  }
  claimed.sort((a, b) => a.start - b.start)
  const pieces: { text: string; marker: Marker | null }[] = []
  let cursor = 0
  for (const range of claimed) {
    if (range.start > cursor) pieces.push({ text: text.slice(cursor, range.start), marker: null })
    pieces.push({ text: text.slice(range.start, range.end), marker: range.marker })
    cursor = range.end
  }
  if (cursor < text.length) pieces.push({ text: text.slice(cursor), marker: null })
  return pieces
}
