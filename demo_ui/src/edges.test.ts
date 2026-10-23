import { describe, expect, it, vi } from 'vitest'
import type { ViewNote } from './api'
import { buildEdges } from './edges'

// 픽스처일 뿐이며 규칙과 무관하다 - 이름은 전부 합성이다
function note(id: string, layer: string, up: string[] = [], down: string[] = []): ViewNote {
  return {
    note_id: id, title: id, layer, group_label: null, body: '', source_doc_id: id, source_layer: layer,
    source_segment_ids: [], upward_links: up, opened_downward_links: down, inserted_at_vault_size: 0,
  }
}

describe('buildEdges', () => {
  it('상향 링크와 열린 하향 조건부 링크를 방향대로 엣지로 만든다', () => {
    const notes = [note('개인1', '개인', ['팀1']), note('팀1', '팀'), note('전사1', '전사', [], ['개인1'])]
    const edges = buildEdges(notes)
    expect(edges.map((e) => [e.kind, e.source, e.target, e.sameLayer])).toEqual([
      ['upward', '개인1', '팀1', false],
      ['downward', '전사1', '개인1', false],
    ])
  })

  it('같은 층 링크는 상향 링크로 만들고 sameLayer 로 표시한다', () => {
    const edges = buildEdges([note('팀1', '팀', ['팀2']), note('팀2', '팀')])
    expect(edges).toHaveLength(1)
    expect(edges[0]).toMatchObject({ kind: 'upward', sameLayer: true })
  })

  it('notes 에 없는 대상의 링크는 엣지가 되지 않고 경고만 남긴다', () => {
    const warn = vi.fn()
    const edges = buildEdges([note('개인1', '개인', ['없는노트'], ['또없는노트'])], warn)
    expect(edges).toEqual([])
    expect(warn).toHaveBeenCalledTimes(2)
  })

  it('엣지 id 는 종류와 양 끝으로 정해져 겹치지 않는다', () => {
    const edges = buildEdges([note('가', '팀', ['나'], ['나']), note('나', '팀')])
    expect(new Set(edges.map((e) => e.id)).size).toBe(2)
  })
})
