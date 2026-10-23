// 사용자 결정 2026-10-21 · 23 : 시연 경로 전용 화면 - 링크 방향 ( 상향 / 열린 하향 조건부 ) 을 엣지로 만든다
import type { ViewNote } from './api'

export type EdgeKind = 'upward' | 'downward'
export type LinkEdge = {
  id: string
  source: string
  target: string
  kind: EdgeKind
  // 같은 층끼리 잇는 링크인지 ( 같은 층 링크는 상향 링크로 기록된다 )
  sameLayer: boolean
}

// 상향 링크 : 노트 → 대상 ( 아래 → 위 ), 열린 하향 조건부 링크 : 노트 → 대상 ( 위 → 아래 )
export function buildEdges(notes: ViewNote[], warn: (message: string) => void = console.warn): LinkEdge[] {
  const byId = new Map(notes.map((note) => [note.note_id, note]))
  const edges: LinkEdge[] = []
  const add = (note: ViewNote, targetId: string, kind: EdgeKind) => {
    const target = byId.get(targetId)
    // 서버가 이미 거르므로 정상이라면 없다 - 있으면 그리지 않고 경고만 남긴다
    if (!target) {
      warn(`응답 notes 에 없는 링크 대상 : ${note.note_id} -> ${targetId} ( ${kind} )`)
      return
    }
    edges.push({
      id: `${kind}:${note.note_id}->${targetId}`,
      source: note.note_id,
      target: targetId,
      kind,
      sameLayer: target.layer === note.layer,
    })
  }
  for (const note of notes) {
    for (const targetId of note.upward_links) add(note, targetId, 'upward')
    for (const targetId of note.opened_downward_links) add(note, targetId, 'downward')
  }
  return edges
}
