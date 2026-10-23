// 사용자 결정 2026-10-23 ( 지침 v3.1 ) : 시연 경로 회의 기능. 회의 · 할 일은 서버가 보는 사람별로 거른 것만 그린다. 보는 사람 선택은 인증이 아니다
// 받은 회의 · 할 일을 화면 모양으로 나누는 순수 함수 - 거르거나 고치지 않는다
import type { Meeting, Task, TaskStatus, Workspace } from './api'

export type DayCell = { date: string; inMonth: boolean }

function pad(value: number, width = 2): string {
  return String(value).padStart(width, '0')
}

// month 는 1 ~ 12 - 시간대에 흔들리지 않게 UTC 로만 계산한다
export function monthGrid(year: number, month: number): DayCell[] {
  if (!Number.isInteger(year) || !Number.isInteger(month) || month < 1 || month > 12) {
    throw new Error(`올바른 달이 아니다 : ${year}-${month}`)
  }
  const first = new Date(Date.UTC(year, month - 1, 1))
  const start = Date.UTC(year, month - 1, 1 - first.getUTCDay())
  const cells: DayCell[] = []
  for (let index = 0; index < 42; index += 1) {
    const day = new Date(start + index * 86_400_000)
    cells.push({
      date: `${pad(day.getUTCFullYear(), 4)}-${pad(day.getUTCMonth() + 1)}-${pad(day.getUTCDate())}`,
      inMonth: day.getUTCMonth() === month - 1,
    })
  }
  return cells
}

// "YYYY-MM-DD" → 그날 시작하는 회의 ( 시작 시각 순, 같으면 id 순 )
export function meetingsByDate(meetings: Meeting[]): Map<string, Meeting[]> {
  const grouped = new Map<string, Meeting[]>()
  for (const meeting of meetings) {
    const date = meeting.starts_at.slice(0, 10)
    grouped.set(date, [...(grouped.get(date) ?? []), meeting])
  }
  for (const [date, list] of grouped) {
    grouped.set(date, [...list].sort((a, b) => a.starts_at.localeCompare(b.starts_at) || a.meeting_id.localeCompare(b.meeting_id)))
  }
  return grouped
}

export const TASK_COLUMN_LABEL: Record<TaskStatus, string> = { todo: '할 일', doing: '진행 중', done: '완료' }

// 기한 순, 기한 없음은 뒤 - 알 수 없는 상태는 어느 칸에 놓을지 알 수 없다
export function taskColumns(tasks: Task[]): Record<TaskStatus, Task[]> {
  const columns: Record<TaskStatus, Task[]> = { todo: [], doing: [], done: [] }
  for (const task of tasks) {
    if (!(task.status in columns)) throw new Error(`알 수 없는 할 일 상태 : ${String(task.status)}`)
    columns[task.status].push(task)
  }
  for (const list of Object.values(columns)) {
    list.sort((a, b) => (a.due ?? '9999-99-99').localeCompare(b.due ?? '9999-99-99') || a.task_id.localeCompare(b.task_id))
  }
  return columns
}

// 전사 / 팀1 / 팀원E
export function workspaceLabel(workspace: Workspace): string {
  return workspace.group ?? workspace.layer
}
