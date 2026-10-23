import { describe, expect, it } from 'vitest'
import type { Mode, ViewNote, ViewResponse } from './api'
import { compareViews } from './compare'

// 픽스처일 뿐이며 규칙과 무관하다 - 이름은 전부 합성이다
function note(id: string, layer: string, title = id): ViewNote {
  return {
    note_id: id, title, layer, group_label: null, body: '', source_doc_id: id, source_layer: layer,
    source_segment_ids: [], upward_links: [], opened_downward_links: [], inserted_at_vault_size: 0,
  }
}

function view(notes: ViewNote[], mode: Mode = 'all_layers'): ViewResponse {
  return {
    mode, viewer_id: '전사', show_names: true, notes,
    counts: { conditional_links_opened: 0, conditional_links_hidden: 0, upward_links_hidden: 0 },
  }
}

describe('compareViews', () => {
  const a = view([note('공통', '팀'), note('가만', '개인'), note('공통2', '전사')])
  const b = view([note('공통', '팀'), note('나만', '전사'), note('공통2', '전사')])

  it('note_id 로 세 칸으로 나눈다', () => {
    const result = compareViews(a, b)
    expect(result.both.map((n) => n.note_id)).toEqual(['공통2', '공통'])
    expect(result.onlyA.map((n) => n.note_id)).toEqual(['가만'])
    expect(result.onlyB.map((n) => n.note_id)).toEqual(['나만'])
  })

  it('각 칸은 층 ( 전사 → 팀 → 개인 ) 다음 제목 순이다', () => {
    const left = view([note('1', '개인', '다'), note('2', '전사', '나'), note('3', '전사', '가'), note('4', '팀', '라')])
    const right = view([])
    expect(compareViews(left, right).onlyA.map((n) => n.title)).toEqual(['가', '나', '라', '다'])
  })

  it('both 에는 a 쪽 노트를 넣는다', () => {
    const left = view([note('같은id', '팀', '왼쪽 제목')])
    const right = view([note('같은id', '팀', '오른쪽 제목')])
    expect(compareViews(left, right).both[0].title).toBe('왼쪽 제목')
  })

  it('모드가 다르면 오류다', () => {
    expect(() => compareViews(view([], 'all_layers'), view([], 'split_by_layer'))).toThrow()
  })

  it('입력 보기를 바꾸지 않는다', () => {
    const before = JSON.stringify(a)
    compareViews(a, b)
    expect(JSON.stringify(a)).toBe(before)
  })
})
