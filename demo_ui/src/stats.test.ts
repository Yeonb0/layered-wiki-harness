import { describe, expect, it } from 'vitest'
import type { ViewNote, ViewResponse } from './api'
import { dashboardStats } from './stats'

// 픽스처일 뿐이며 규칙과 무관하다 - 이름은 전부 합성이다
function note(id: string, layer: string, up: string[] = [], down: string[] = []): ViewNote {
  return {
    note_id: id, title: id, layer, group_label: null, body: '', source_doc_id: id, source_layer: layer,
    source_segment_ids: [], upward_links: up, opened_downward_links: down, inserted_at_vault_size: 0,
  }
}

function view(notes: ViewNote[], hiddenDown = 0, hiddenUp = 0): ViewResponse {
  return {
    mode: 'all_layers', viewer_id: '전사', show_names: true, notes,
    counts: { conditional_links_opened: 0, conditional_links_hidden: hiddenDown, upward_links_hidden: hiddenUp },
  }
}

describe('dashboardStats', () => {
  it('층별 노트 수와 전체 수를 센다', () => {
    const stats = dashboardStats(view([note('가', '전사'), note('나', '팀'), note('다', '팀'), note('라', '개인')]))
    expect(stats.notesByLayer).toEqual({ 전사: 1, 팀: 2, 개인: 1 })
    expect(stats.totalNotes).toBe(4)
  })

  it('보이는 상향 링크와 열린 하향 조건부 링크는 응답의 노트에서 센다', () => {
    const stats = dashboardStats(view([note('가', '전사', [], ['나', '다']), note('나', '팀', ['가']), note('다', '개인', ['나', '가'])]))
    expect(stats.upwardLinks).toBe(3)
    expect(stats.openedDownward).toBe(2)
  })

  it('가려진 링크 수는 서버가 센 값을 그대로 쓴다', () => {
    const stats = dashboardStats(view([], 4, 2))
    expect(stats.hiddenDownward).toBe(4)
    expect(stats.hiddenUpward).toBe(2)
    expect(stats.notesByLayer).toEqual({ 전사: 0, 팀: 0, 개인: 0 })
  })

  it('층 순서에 없는 값은 오류다', () => {
    expect(() => dashboardStats(view([note('가', '없는층')]))).toThrow()
  })
})
