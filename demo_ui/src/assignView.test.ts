import { describe, expect, it } from 'vitest'
import type { Task } from './api'
import { droppedReasonLabel, groupByAssignee, pendingProposals, problemLabel } from './assignView'

// 픽스처일 뿐이며 규칙과 무관하다 - 합성 값이다
function task(id: string, assignee: string, source: Task['source'] = 'agent_proposal'): Task {
  return {
    task_id: id, meeting_id: 'm0007', title: id, workspace: { layer: '팀', group: '팀1' }, assignee, due: null, status: 'todo', source, progress: [],
  }
}

describe('groupByAssignee', () => {
  it('참석자 순서를 유지하고 할 일이 없는 참석자는 뺀다', () => {
    const groups = groupByAssignee([task('t3', '팀원B'), task('t1', '팀원A'), task('t2', '팀원B')], ['팀원A', '팀원B', '팀원E'])
    expect(groups.map((g) => [g.assignee, g.tasks.map((t) => t.task_id)])).toEqual([['팀원A', ['t1']], ['팀원B', ['t3', 't2']]])
  })

  it('참석자 밖 담당자는 뒤에 붙는다', () => {
    const groups = groupByAssignee([task('t1', '팀원Z'), task('t2', '팀원A')], ['팀원A', '팀원B'])
    expect(groups.map((g) => g.assignee)).toEqual(['팀원A', '팀원Z'])
  })

  it('할 일이 없으면 비어 있다', () => {
    expect(groupByAssignee([], ['팀원A'])).toEqual([])
  })
})

describe('라벨', () => {
  it('버려진 이유 네 가지', () => {
    expect(droppedReasonLabel('evidence_not_in_minutes')).toBe('근거가 회의록에 없음')
    expect(droppedReasonLabel('assignee_not_attendee')).toBe('담당자가 참석자가 아님')
    expect(droppedReasonLabel('invalid_task')).toBe('형식 오류')
    expect(droppedReasonLabel('too_many_tasks')).toBe('10개 초과')
  })

  it('고친 것 두 가지', () => {
    expect(problemLabel('due_not_in_minutes')).toBe('회의록에 없는 기한이라 비움')
    expect(problemLabel('due_bad_format')).toBe('기한 형식 오류라 비움')
  })

  it('알 수 없는 값은 원문 그대로 보이고 알 수 없다고 덧붙인다', () => {
    expect(droppedReasonLabel('새_이유')).toBe('새_이유 ( 알 수 없는 이유 )')
    expect(problemLabel('새_문제')).toBe('새_문제 ( 알 수 없는 이유 )')
  })
})

describe('pendingProposals', () => {
  it('에이전트 제안 상태의 할 일만 남긴다', () => {
    const tasks = [task('t1', '팀원A'), task('t2', '팀원A', 'agent_confirmed'), task('t3', '팀원A', 'human')]
    expect(pendingProposals(tasks).map((t) => t.task_id)).toEqual(['t1'])
  })
})
