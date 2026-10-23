import { describe, expect, it } from 'vitest'
import type { ViewNote } from './api'
import { layoutNotes } from './layout'

// 픽스처일 뿐이며 규칙과 무관하다 - 이름은 전부 합성이다
function note(id: string, layer: string, group: string | null, order: number): ViewNote {
  return {
    note_id: id, title: `제목 ${id}`, layer, group_label: group, body: '합성 본문', source_doc_id: `문서 ${id}`,
    source_layer: layer, source_segment_ids: [`${id}-s1`], upward_links: [], opened_downward_links: [],
    inserted_at_vault_size: order,
  }
}

const NOTES = [
  note('개인가2', '개인', '샘플가', 5),
  note('개인가1', '개인', '샘플가', 2),
  note('개인나1', '개인', '샘플나', 1),
  note('팀가1', '팀', '팀가', 3),
  note('팀나1', '팀', '팀나', 4),
  note('전사1', '전사', null, 0),
]

function byId(id: string) {
  const found = layoutNotes(NOTES).nodes.find((n) => n.note.note_id === id)
  if (!found) throw new Error(`노드 없음 : ${id}`)
  return found
}

describe('layoutNotes', () => {
  it('전사 띠가 팀 띠 위에, 팀 띠가 개인 띠 위에 있다', () => {
    const { nodes } = layoutNotes(NOTES)
    const ys = (layer: string) => nodes.filter((n) => n.note.layer === layer).map((n) => n.y)
    expect(Math.max(...ys('전사'))).toBeLessThan(Math.min(...ys('팀')))
    expect(Math.max(...ys('팀'))).toBeLessThan(Math.min(...ys('개인')))
  })

  it('같은 칸 안에서는 inserted_at_vault_size 순서로 놓는다', () => {
    const first = byId('개인가1')
    const second = byId('개인가2')
    expect([first.y, first.x]).toSatisfy(([y, x]: number[]) => y < second.y || (y === second.y && x < second.x))
    expect(first.cell).toBe('샘플가')
  })

  it('다른 group_label 은 다른 x 칸에 놓인다', () => {
    const personal = layoutNotes(NOTES).nodes.filter((n) => n.band === '개인')
    const left = personal.filter((n) => n.cell === '샘플가').map((n) => n.x)
    const right = personal.filter((n) => n.cell === '샘플나').map((n) => n.x)
    expect(Math.max(...left)).toBeLessThan(Math.min(...right))
    expect(byId('팀가1').x).toBeLessThan(byId('팀나1').x)
  })

  it('칸 이름은 그룹이 없으면 층 이름이다', () => {
    expect(byId('전사1').cell).toBe('전사')
    const { cells } = layoutNotes(NOTES)
    expect(cells.filter((c) => c.band === '개인').map((c) => c.label)).toEqual(['샘플가', '샘플나'])
  })

  it('층 순서에 없는 값은 오류다', () => {
    expect(() => layoutNotes([note('x', '없는층', null, 0)])).toThrow()
  })

  it('노트가 없어도 세 띠를 돌려준다', () => {
    const layout = layoutNotes([])
    expect(layout.bands.map((b) => b.band)).toEqual(['전사', '팀', '개인'])
    expect(layout.nodes).toEqual([])
  })
})

describe('layoutNotes 띠 · 칸 이름 자리', () => {
  it('칸은 띠 이름 줄 아래에서 시작한다', () => {
    const { bands, cells } = layoutNotes(NOTES)
    for (const cell of cells) {
      const band = bands.find((b) => b.band === cell.band)!
      expect(cell.y).toBeGreaterThan(band.y)
      expect(cell.y + cell.height).toBeLessThanOrEqual(band.y + band.height)
    }
  })

  it('노트가 없는 띠만 empty 로 표시한다', () => {
    const layout = layoutNotes([note('팀가1', '팀', '팀가', 0)])
    expect(layout.bands.map((b) => [b.band, b.empty])).toEqual([['전사', true], ['팀', false], ['개인', true]])
  })
})
