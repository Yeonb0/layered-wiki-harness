import { describe, expect, it } from 'vitest'
import type { Meeting, Task } from './api'
import { formatAt, formatRange, isOverdue, localToday, meetingsByDate, monthGrid, taskColumns, workspaceLabel } from './meetingsView'

// 픽스처일 뿐이며 규칙과 무관하다 - 합성 값이다
function meeting(id: string, startsAt: string): Meeting {
  return {
    meeting_id: id, title: id, starts_at: startsAt, ends_at: startsAt, workspace: { layer: '전사', group: null }, attendees: [],
    agenda: [], minutes_doc_id: null, status: 'scheduled', created_by: null, updated_at: null,
  }
}

function task(id: string, status: string, due: string | null): Task {
  return {
    task_id: id, meeting_id: null, title: id, workspace: { layer: '전사', group: null }, assignee: '합성', due,
    status: status as Task['status'], source: 'human', progress: [],
  }
}

describe('monthGrid', () => {
  it('2026-10 은 42칸이고 첫 칸은 2026-09-27 ( 일요일 ) 이다', () => {
    const cells = monthGrid(2026, 10)
    expect(cells).toHaveLength(42)
    expect(cells[0]).toEqual({ date: '2026-09-27', inMonth: false })
    expect(cells[4]).toEqual({ date: '2026-10-01', inMonth: true })
    expect(cells[34]).toEqual({ date: '2026-10-31', inMonth: true })
    expect(cells[41]).toEqual({ date: '2026-11-07', inMonth: false })
  })

  it('1일이 일요일인 달은 첫 칸이 1일이다', () => {
    const cells = monthGrid(2026, 11)
    expect(cells[0]).toEqual({ date: '2026-11-01', inMonth: true })
  })

  it('해가 바뀌는 달도 이어진다', () => {
    const cells = monthGrid(2026, 12)
    expect(cells.some((cell) => cell.date === '2027-01-01' && !cell.inMonth)).toBe(true)
    expect(() => monthGrid(2026, 13)).toThrow()
  })
})

describe('meetingsByDate', () => {
  it('날짜로 묶고 시작 시각 순으로 놓는다', () => {
    const grouped = meetingsByDate([meeting('b', '2026-10-05T15:00'), meeting('a', '2026-10-05T09:00'), meeting('c', '2026-10-06T09:00')])
    expect(grouped.get('2026-10-05')?.map((m) => m.meeting_id)).toEqual(['a', 'b'])
    expect(grouped.get('2026-10-06')?.map((m) => m.meeting_id)).toEqual(['c'])
    expect(grouped.get('2026-10-07')).toBeUndefined()
  })
})

describe('taskColumns', () => {
  it('상태로 나누고 기한 순, 기한 없음은 뒤에 놓는다', () => {
    const columns = taskColumns([task('t3', 'todo', null), task('t1', 'todo', '2026-10-20'), task('t2', 'todo', '2026-10-10'), task('t4', 'done', null)])
    expect(columns.todo.map((t) => t.task_id)).toEqual(['t2', 't1', 't3'])
    expect(columns.doing).toEqual([])
    expect(columns.done.map((t) => t.task_id)).toEqual(['t4'])
  })

  it('알 수 없는 상태는 오류다', () => {
    expect(() => taskColumns([task('t1', '끝', null)])).toThrow('알 수 없는 할 일 상태')
  })
})

describe('workspaceLabel', () => {
  it('전사 · 팀 · 개인 표시', () => {
    expect(workspaceLabel({ layer: '전사', group: null })).toBe('전사')
    expect(workspaceLabel({ layer: '팀', group: '팀1' })).toBe('팀1')
    expect(workspaceLabel({ layer: '개인', group: '팀원E' })).toBe('팀원E')
  })
})

describe('formatRange · formatAt', () => {
  it('같은 날이면 끝에는 시각만 쓴다 ( 2026-10-14 는 수요일 )', () => {
    expect(formatRange('2026-10-14T14:00', '2026-10-14T15:00')).toBe('2026-10-14 ( 수 ) 14:00 ~ 15:00')
  })

  it('다른 날이면 끝에도 날짜와 요일을 쓴다', () => {
    expect(formatRange('2026-10-14T14:00', '2026-10-15T09:00')).toBe('2026-10-14 ( 수 ) 14:00 ~ 2026-10-15 ( 목 ) 09:00')
  })

  it('일요일과 토요일', () => {
    expect(formatRange('2026-10-11T10:00', '2026-10-17T10:00')).toBe('2026-10-11 ( 일 ) 10:00 ~ 2026-10-17 ( 토 ) 10:00')
  })

  it('형식이 다르면 오류다', () => {
    expect(() => formatRange('2026-10-14 14:00', '2026-10-14T15:00')).toThrow('형식')
    expect(() => formatRange('2026-10-14T14:00', '내일')).toThrow('형식')
    expect(() => formatAt('2026-10-23')).toThrow('형식')
  })

  it('formatAt 은 T 를 공백으로 바꾼다', () => {
    expect(formatAt('2026-10-23T15:57')).toBe('2026-10-23 15:57')
  })
})

describe('isOverdue', () => {
  const today = '2026-10-23'
  it('하루 지났고 끝나지 않았으면 true', () => {
    expect(isOverdue({ due: '2026-10-22', status: 'todo' }, today)).toBe(true)
    expect(isOverdue({ due: '2026-10-22', status: 'doing' }, today)).toBe(true)
  })

  it('당일 · 기한 없음 · 완료는 false', () => {
    expect(isOverdue({ due: '2026-10-23', status: 'todo' }, today)).toBe(false)
    expect(isOverdue({ due: null, status: 'todo' }, today)).toBe(false)
    expect(isOverdue({ due: '2026-10-01', status: 'done' }, today)).toBe(false)
  })
})

describe('localToday', () => {
  it('지역 날짜를 YYYY-MM-DD 로 만든다', () => {
    expect(localToday(new Date(2026, 9, 3, 23, 59))).toBe('2026-10-03')
  })
})
