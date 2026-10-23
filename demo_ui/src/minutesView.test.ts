import { describe, expect, it } from 'vitest'
import type { ProposalNote } from './api'
import { canApprove, proposalCounts, statusLabel } from './minutesView'

// 픽스처일 뿐이며 규칙과 무관하다 - 합성 값이다
function note(layer: string | null, decision: 'approve' | 'reject' | null): ProposalNote {
  return {
    note_index: 0, title: '합성', layer, group_label: null, body: null, source_segment_ids: [], upward_links: [], downward_links: [],
    hidden_links: 0, problems: [], decision: decision === null ? null : { decision, by: '합성', at: '2026-10-23T10:00' },
  }
}

describe('proposalCounts', () => {
  it('승인 · 반려 · 미결을 센다', () => {
    const counts = proposalCounts({ notes: [note('팀', 'approve'), note('팀', 'reject'), note(null, 'reject'), note('팀', null), note('팀', null)] })
    expect(counts).toEqual({ approved: 1, rejected: 2, pending: 2 })
  })

  it('노트가 없으면 모두 0 이다', () => {
    expect(proposalCounts({ notes: [] })).toEqual({ approved: 0, rejected: 0, pending: 0 })
  })
})

describe('canApprove', () => {
  it('배치된 미결 노트만 승인할 수 있다', () => {
    expect(canApprove(note('팀', null))).toBe(true)
    expect(canApprove(note(null, null))).toBe(false)
    expect(canApprove(note('팀', 'approve'))).toBe(false)
    expect(canApprove(note('팀', 'reject'))).toBe(false)
  })
})

describe('statusLabel', () => {
  it('네 상태의 이름', () => {
    expect(statusLabel('running')).toBe('처리 중')
    expect(statusLabel('awaiting_approval')).toBe('승인 대기')
    expect(statusLabel('decided')).toBe('결정 완료')
    expect(statusLabel('failed')).toBe('실패')
  })

  it('알 수 없는 상태는 오류다', () => {
    expect(() => statusLabel('끝')).toThrow('알 수 없는 제안 상태')
  })
})
