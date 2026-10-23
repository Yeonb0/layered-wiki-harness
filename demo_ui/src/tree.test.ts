import { describe, expect, it } from 'vitest'
import type { ViewNote } from './api'
import { buildTree } from './tree'

// 픽스처일 뿐이며 규칙과 무관하다 - 이름은 전부 합성이다
function note(id: string, layer: string, group: string | null, order: number): ViewNote {
  return {
    note_id: id, title: `제목 ${id}`, layer, group_label: group, body: '', source_doc_id: id, source_layer: layer,
    source_segment_ids: [], upward_links: [], opened_downward_links: [], inserted_at_vault_size: order,
  }
}

describe('buildTree', () => {
  const notes = [
    note('개인나2', '개인', '샘플나', 7),
    note('개인가1', '개인', '샘플가', 3),
    note('개인나1', '개인', '샘플나', 2),
    note('팀나1', '팀', '팀나', 5),
    note('팀가1', '팀', '팀가', 4),
    note('전사2', '전사', null, 1),
    note('전사1', '전사', null, 0),
  ]

  it('층 순서는 전사 · 팀 · 개인이다', () => {
    expect(buildTree(notes).map((layer) => layer.layer)).toEqual(['전사', '팀', '개인'])
  })

  it('그룹은 이름순이고 층마다 노트 수를 센다', () => {
    const tree = buildTree(notes)
    expect(tree[1].groups.map((g) => g.label)).toEqual(['팀가', '팀나'])
    expect(tree[2].groups.map((g) => g.label)).toEqual(['샘플가', '샘플나'])
    expect(tree.map((layer) => layer.count)).toEqual([2, 2, 3])
  })

  it('칸 안의 노트는 inserted_at_vault_size 순서다', () => {
    const personal = buildTree(notes)[2].groups.find((g) => g.label === '샘플나')!
    expect(personal.notes.map((n) => n.note_id)).toEqual(['개인나1', '개인나2'])
    expect(buildTree(notes)[0].groups[0].notes.map((n) => n.note_id)).toEqual(['전사1', '전사2'])
  })

  it('그룹이 없는 노트 ( 전사 ) 는 label 이 null 인 그룹 하나에 들어간다', () => {
    const company = buildTree(notes)[0]
    expect(company.groups).toHaveLength(1)
    expect(company.groups[0].label).toBeNull()
  })

  it('노트가 없는 층도 빈 채로 남긴다', () => {
    const tree = buildTree([note('팀가1', '팀', '팀가', 0)])
    expect(tree.map((layer) => [layer.layer, layer.count, layer.groups.length])).toEqual([
      ['전사', 0, 0],
      ['팀', 1, 1],
      ['개인', 0, 0],
    ])
    expect(buildTree([]).every((layer) => layer.count === 0)).toBe(true)
  })

  it('층 순서에 없는 값은 오류다', () => {
    expect(() => buildTree([note('x', '없는층', null, 0)])).toThrow()
  })

  it('입력 배열을 바꾸지 않는다', () => {
    const copy = [...notes]
    buildTree(notes)
    expect(notes).toEqual(copy)
  })
})
