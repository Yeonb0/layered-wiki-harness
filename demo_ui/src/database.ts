// 사용자 결정 2026-10-23 : 대시보드는 노션 느낌 ( 데이터베이스 표 · 보드 · 토글 ). 정렬 · 거르기는 서버가 거른 보기 안에서만 하는 화면 표시다
import type { ViewResponse } from './api'
import { BANDS, type Band } from './layout'
import { findMarkers, type MarkerKind } from './markers'

export type Row = {
  noteId: string
  title: string
  layer: string
  group: string | null
  // doc_id 끝 4자리
  sourceDoc: string
  segments: number
  upward: number
  openedDown: number
  markers: { text: string; kind: MarkerKind }[]
}

// showNames 가 false 면 본문이 가려져 표지를 찾을 수 없으므로 markers 는 빈 목록이다
export function toRows(view: ViewResponse, showNames: boolean): Row[] {
  return view.notes.map((note) => ({
    noteId: note.note_id,
    title: note.title,
    layer: note.layer,
    group: note.group_label,
    sourceDoc: note.source_doc_id.slice(-4),
    segments: note.source_segment_ids.length,
    upward: note.upward_links.length,
    openedDown: note.opened_downward_links.length,
    markers: showNames ? findMarkers(note).map((hit) => ({ text: hit.marker.text, kind: hit.kind })) : [],
  }))
}

export type SortKey = 'title' | 'layer' | 'group' | 'sourceDoc' | 'segments' | 'upward' | 'openedDown' | 'markers'

function layerIndex(layer: string): number {
  const index = (BANDS as readonly string[]).indexOf(layer)
  // 층 순서에 없는 값은 어디에 놓을지 알 수 없다
  if (index < 0) throw new Error(`알 수 없는 층 : ${layer}`)
  return index
}

function compareBy(a: Row, b: Row, key: SortKey): number {
  switch (key) {
    case 'layer':
      return layerIndex(a.layer) - layerIndex(b.layer)
    case 'segments':
    case 'upward':
    case 'openedDown':
      return a[key] - b[key]
    case 'markers':
      return a.markers.length - b.markers.length
    default:
      // 그룹이 없는 노트 ( 전사 ) 는 빈 문자열로 본다
      return (a[key] ?? '').localeCompare(b[key] ?? '', 'ko')
  }
}

// 원본을 바꾸지 않는다 - 같은 값이면 방향과 상관없이 제목 순이다 ( 안정 정렬 )
export function sortRows(rows: Row[], key: SortKey, dir: 'asc' | 'desc'): Row[] {
  const sign = dir === 'asc' ? 1 : -1
  return [...rows].sort((a, b) => sign * compareBy(a, b, key) || a.title.localeCompare(b.title, 'ko'))
}

// 빈 집합이면 전부 보인다
export function filterByLayer(rows: Row[], layers: Set<string>): Row[] {
  return layers.size === 0 ? [...rows] : rows.filter((row) => layers.has(row.layer))
}

export function boardColumns(rows: Row[]): Record<Band, Row[]> {
  const columns = { 전사: [], 팀: [], 개인: [] } as Record<Band, Row[]>
  for (const row of rows) {
    layerIndex(row.layer)
    columns[row.layer as Band].push(row)
  }
  return columns
}
