// 사용자 요청 2026-10-23 : 그래프는 옵시디언 그래프 뷰처럼 움직이고 연결이 강조되게. 지침 7절 : 층 · 링크 방향은 계속 드러낸다
import type { ViewResponse } from './api'
import type { LinkEdge } from './edges'
import { BANDS } from './layout'

export type GNode = {
  id: string
  title: string
  layer: string
  group: string | null
  degree: number
  radius: number
}

function bandIndex(layer: string): number {
  const index = (BANDS as readonly string[]).indexOf(layer)
  // 층 순서에 없는 값은 어느 띠에 놓을지 알 수 없다
  if (index < 0) throw new Error(`알 수 없는 층 : ${layer}`)
  return index
}

// degree = 그 노드에 닿는 엣지 수 ( 방향 무관 ), radius = 6 + 2 × √degree ( 소수 1자리 반올림 )
export function graphNodes(view: ViewResponse, edges: LinkEdge[]): GNode[] {
  const degree = new Map<string, number>()
  for (const edge of edges) {
    degree.set(edge.source, (degree.get(edge.source) ?? 0) + 1)
    degree.set(edge.target, (degree.get(edge.target) ?? 0) + 1)
  }
  return view.notes.map((note) => {
    bandIndex(note.layer)
    const count = degree.get(note.note_id) ?? 0
    return {
      id: note.note_id,
      title: note.title,
      layer: note.layer,
      group: note.group_label,
      degree: count,
      radius: Math.round((6 + 2 * Math.sqrt(count)) * 10) / 10,
    }
  })
}

// 자기 자신을 포함한 이웃 id 집합 - 방향 무관
export function neighbors(edges: LinkEdge[], id: string): Set<string> {
  const out = new Set<string>([id])
  for (const edge of edges) {
    if (edge.source === id) out.add(edge.target)
    if (edge.target === id) out.add(edge.source)
  }
  return out
}

// 높이를 3등분한 각 칸의 가운데 - 전사가 위
export function layerY(layer: string, height: number): number {
  return (bandIndex(layer) + 0.5) * (height / BANDS.length)
}

export type Placed = GNode & { x?: number; y?: number }

// 보기가 바뀌어도 같은 id 노드는 이전 좌표를 이어 받는다 - 없는 id 는 좌표 없이 돌려준다
export function keepPositions(prev: Map<string, { x: number; y: number }>, nodes: GNode[]): Placed[] {
  return nodes.map((node) => {
    const old = prev.get(node.id)
    return old ? { ...node, x: old.x, y: old.y } : { ...node }
  })
}
