// 사용자 결정 2026-10-23 ( 지침 v3.1 · 3절 27 ) : 할 일 배정은 회의록 승인 뒤 버튼으로 도는 별도 역할. 결과는 에이전트 제안으로 표시하고 사람이 확정 / 버린다. 확정 뒤 팀원이 진행 기록을 덧붙인다
// 서버가 준 할 일 · 사유를 화면 모양으로 나누는 순수 함수 - 숨기거나 고치지 않는다
import type { Task } from './api'

// 참석자 순서를 유지한다 - 참석자 밖 담당자는 만난 순서로 뒤에 붙고 할 일이 없는 참석자는 빠진다
export function groupByAssignee(tasks: Task[], attendees: string[]): { assignee: string; tasks: Task[] }[] {
  const order = [...attendees]
  for (const task of tasks) if (!order.includes(task.assignee)) order.push(task.assignee)
  return order
    .map((assignee) => ({ assignee, tasks: tasks.filter((task) => task.assignee === assignee) }))
    .filter((group) => group.tasks.length > 0)
}

const UNKNOWN = '( 알 수 없는 이유 )'

const DROPPED_LABEL: Record<string, string> = {
  evidence_not_in_minutes: '근거가 회의록에 없음',
  assignee_not_attendee: '담당자가 참석자가 아님',
  invalid_task: '형식 오류',
  too_many_tasks: '10개 초과',
}

const PROBLEM_LABEL: Record<string, string> = {
  due_not_in_minutes: '회의록에 없는 기한이라 비움',
  due_bad_format: '기한 형식 오류라 비움',
}

export function droppedReasonLabel(reason: string): string {
  return DROPPED_LABEL[reason] ?? `${reason} ${UNKNOWN}`
}

export function problemLabel(problem: string): string {
  return PROBLEM_LABEL[problem] ?? `${problem} ${UNKNOWN}`
}

export function pendingProposals(tasks: Task[]): Task[] {
  return tasks.filter((task) => task.source === 'agent_proposal')
}
