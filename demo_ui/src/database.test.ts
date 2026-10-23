import { describe, expect, it } from 'vitest'
import type { ViewNote, ViewResponse } from './api'
import { boardColumns, filterByLayer, sortRows, toRows, type Row } from './database'

// 픽스처일 뿐이며 규칙과 무관하다 - 이름은 전부 합성이다
function note(id: string, layer: string, group: string | null, extra: Partial<ViewNote> = {}): ViewNote {
  return {
    note_id: id, title: `제목 ${id}`, layer, group_label: group, body: '', source_doc_id: `문서번호${id}`, source_layer: layer,
    source_segment_ids: [], upward_links: [], opened_downward_links: [], inserted_at_vault_size: 0, ...extra,
  }
}

function view(notes: ViewNote[]): ViewResponse {
  return {
    mode: 'all_layers', viewer_id: '전사', show_names: true, notes,
    counts: { conditional_links_opened: 0, conditional_links_hidden: 0, upward_links_hidden: 0 },
  }
}

function row(title: string, extra: Partial<Row> = {}): Row {
  return { noteId: title, title, layer: '팀', group: null, sourceDoc: '0000', segments: 0, upward: 0, openedDown: 0, markers: [], ...extra }
}

describe('toRows', () => {
  const notes = [
    note('가', '팀', '팀1', { body: '붉은 매듭 메모', source_segment_ids: ['s1', 's2'], upward_links: ['나'], opened_downward_links: ['다', '라'] }),
    note('나', '전사', null),
  ]

  it('노트마다 한 행을 만들고 출처 문서는 끝 4자리다', () => {
    const rows = toRows(view(notes), true)
    expect(rows).toHaveLength(2)
    expect(rows[0]).toMatchObject({ noteId: '가', layer: '팀', group: '팀1', sourceDoc: '서번호가', segments: 2, upward: 1, openedDown: 2 })
    expect(rows[1].group).toBeNull()
  })

  it('showNames 가 true 면 표지 ( 표현 · 판정 ) 를 담는다', () => {
    expect(toRows(view(notes), true)[0].markers).toEqual([{ text: '붉은 매듭', kind: 'home' }])
  })

  it('showNames 가 false 면 markers 는 빈 목록이다', () => {
    expect(toRows(view(notes), false).every((r) => r.markers.length === 0)).toBe(true)
  })

  it('노트가 없으면 빈 목록이다', () => {
    expect(toRows(view([]), true)).toEqual([])
  })
})

describe('sortRows', () => {
  it('layer 는 전사 → 팀 → 개인 순서다', () => {
    const rows = [row('가', { layer: '개인' }), row('나', { layer: '전사' }), row('다', { layer: '팀' })]
    expect(sortRows(rows, 'layer', 'asc').map((r) => r.layer)).toEqual(['전사', '팀', '개인'])
    expect(sortRows(rows, 'layer', 'desc').map((r) => r.layer)).toEqual(['개인', '팀', '전사'])
  })

  it('숫자 열은 값으로, markers 는 개수로 정렬한다', () => {
    const rows = [row('가', { segments: 3 }), row('나', { segments: 1 }), row('다', { segments: 2 })]
    expect(sortRows(rows, 'segments', 'asc').map((r) => r.segments)).toEqual([1, 2, 3])
    const marked = [row('가', { markers: [{ text: 'a', kind: 'up' }] }), row('나'), row('다', { markers: [{ text: 'a', kind: 'up' }, { text: 'b', kind: 'home' }] })]
    expect(sortRows(marked, 'markers', 'desc').map((r) => r.title)).toEqual(['다', '가', '나'])
  })

  it('문자열 열은 ko 순서이고 그룹이 없으면 빈 문자열로 본다', () => {
    const rows = [row('가', { group: '팀2' }), row('나', { group: null }), row('다', { group: '팀1' })]
    expect(sortRows(rows, 'group', 'asc').map((r) => r.group)).toEqual([null, '팀1', '팀2'])
  })

  it('같은 값이면 방향과 상관없이 제목 순이다', () => {
    const rows = [row('다', { segments: 1 }), row('가', { segments: 1 }), row('나', { segments: 1 })]
    expect(sortRows(rows, 'segments', 'asc').map((r) => r.title)).toEqual(['가', '나', '다'])
    expect(sortRows(rows, 'segments', 'desc').map((r) => r.title)).toEqual(['가', '나', '다'])
  })

  it('원본을 바꾸지 않고 빈 목록도 다룬다', () => {
    const rows = [row('나'), row('가')]
    sortRows(rows, 'title', 'asc')
    expect(rows.map((r) => r.title)).toEqual(['나', '가'])
    expect(sortRows([], 'title', 'asc')).toEqual([])
  })

  it('알 수 없는 층으로 layer 정렬을 하면 오류다', () => {
    expect(() => sortRows([row('가', { layer: '없는층' }), row('나')], 'layer', 'asc')).toThrow()
  })
})

describe('filterByLayer', () => {
  const rows = [row('가', { layer: '전사' }), row('나', { layer: '팀' }), row('다', { layer: '개인' })]

  it('빈 집합이면 전부 돌려준다', () => {
    expect(filterByLayer(rows, new Set())).toEqual(rows)
  })

  it('켠 층의 행만 남긴다', () => {
    expect(filterByLayer(rows, new Set(['팀', '개인'])).map((r) => r.title)).toEqual(['나', '다'])
  })

  it('원본 배열을 돌려주지 않고 복사한다', () => {
    expect(filterByLayer(rows, new Set())).not.toBe(rows)
  })
})

describe('boardColumns', () => {
  it('세 칸을 전사 → 팀 → 개인 순서로 만들고 입력 순서를 지킨다', () => {
    const columns = boardColumns([row('가', { layer: '개인' }), row('나', { layer: '팀' }), row('다', { layer: '개인' })])
    expect(Object.keys(columns)).toEqual(['전사', '팀', '개인'])
    expect(columns.전사).toEqual([])
    expect(columns.개인.map((r) => r.title)).toEqual(['가', '다'])
  })

  it('알 수 없는 층은 오류다', () => {
    expect(() => boardColumns([row('가', { layer: '없는층' })])).toThrow()
  })

  it('빈 목록이면 세 칸 모두 비어 있다', () => {
    expect(boardColumns([])).toEqual({ 전사: [], 팀: [], 개인: [] })
  })
})
