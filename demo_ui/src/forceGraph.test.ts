import { describe, expect, it } from 'vitest'
import type { ViewNote, ViewResponse } from './api'
import type { LinkEdge } from './edges'
import { graphNodes, keepPositions, layerY, neighbors } from './forceGraph'

// 픽스처일 뿐이며 규칙과 무관하다 - 이름은 전부 합성이다
function note(id: string, layer: string, group: string | null = null): ViewNote {
  return {
    note_id: id, title: `제목 ${id}`, layer, group_label: group, body: '', source_doc_id: id, source_layer: layer,
    source_segment_ids: [], upward_links: [], opened_downward_links: [], inserted_at_vault_size: 0,
  }
}

function view(notes: ViewNote[]): ViewResponse {
  return {
    mode: 'all_layers', viewer_id: '전사', show_names: true, notes,
    counts: { conditional_links_opened: 0, conditional_links_hidden: 0, upward_links_hidden: 0 },
  }
}

function edge(source: string, target: string, kind: 'upward' | 'downward' = 'upward'): LinkEdge {
  return { id: `${kind}:${source}->${target}`, source, target, kind, sameLayer: false }
}

describe('graphNodes', () => {
  const edges = [edge('가', '나'), edge('다', '가', 'downward'), edge('나', '다')]

  it('degree 는 닿는 엣지 수 ( 방향 무관 ) 이다', () => {
    const nodes = graphNodes(view([note('가', '팀'), note('나', '전사'), note('다', '개인'), note('라', '개인')]), edges)
    expect(nodes.map((n) => [n.id, n.degree])).toEqual([['가', 2], ['나', 2], ['다', 2], ['라', 0]])
  })

  it('radius = 6 + 2 × √degree 를 소수 1자리로 반올림한다', () => {
    const nodes = graphNodes(view([note('가', '팀'), note('나', '전사'), note('라', '개인')]), edges)
    expect(nodes[0].radius).toBe(8.8)
    expect(nodes[2].radius).toBe(6)
    const many = Array.from({ length: 9 }, (_, i) => edge('가', `x${i}`))
    expect(graphNodes(view([note('가', '팀')]), many)[0].radius).toBe(12)
  })

  it('제목 · 층 · 그룹을 그대로 옮기고 노트가 없으면 빈 목록이다', () => {
    expect(graphNodes(view([note('가', '팀', '팀1')]), [])[0]).toMatchObject({ id: '가', title: '제목 가', layer: '팀', group: '팀1' })
    expect(graphNodes(view([]), edges)).toEqual([])
  })

  it('층 순서에 없는 층은 오류다', () => {
    expect(() => graphNodes(view([note('가', '없는층')]), [])).toThrow()
  })
})

describe('neighbors', () => {
  const edges = [edge('가', '나'), edge('다', '가', 'downward'), edge('라', '마')]

  it('자기 자신을 포함한다', () => {
    expect(neighbors(edges, '가').has('가')).toBe(true)
  })

  it('방향과 상관없이 양쪽 이웃을 모은다', () => {
    expect(neighbors(edges, '가')).toEqual(new Set(['가', '나', '다']))
    expect(neighbors(edges, '나')).toEqual(new Set(['나', '가']))
  })

  it('고립 노드는 자기 자신뿐이다', () => {
    expect(neighbors(edges, '바')).toEqual(new Set(['바']))
    expect(neighbors([], '가')).toEqual(new Set(['가']))
  })
})

describe('layerY', () => {
  it('높이를 3등분한 각 칸의 가운데이고 전사가 위다', () => {
    expect(layerY('전사', 300)).toBe(50)
    expect(layerY('팀', 300)).toBe(150)
    expect(layerY('개인', 300)).toBe(250)
    expect(layerY('전사', 300)).toBeLessThan(layerY('팀', 300))
  })

  it('알 수 없는 층은 오류다', () => {
    expect(() => layerY('없는층', 300)).toThrow()
  })
})

describe('keepPositions', () => {
  const nodes = graphNodes(view([note('가', '팀'), note('나', '전사')]), [])

  it('같은 id 는 이전 좌표를 이어 받고 없는 id 는 좌표가 없다', () => {
    const kept = keepPositions(new Map([['가', { x: 10, y: 20 }], ['다', { x: 1, y: 2 }]]), nodes)
    expect(kept[0]).toMatchObject({ id: '가', x: 10, y: 20 })
    expect(kept[1].id).toBe('나')
    expect('x' in kept[1]).toBe(false)
  })

  it('이전 좌표가 비어 있으면 모두 좌표가 없고 원본 노드를 바꾸지 않는다', () => {
    const kept = keepPositions(new Map(), nodes)
    expect(kept.every((n) => !('x' in n))).toBe(true)
    expect('x' in nodes[0]).toBe(false)
  })
})
