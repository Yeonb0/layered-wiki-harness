// 사용자 결정 2026-10-23 ( 지침 v3.1 ) : 시연 경로 회의 기능. 회의 · 할 일은 서버가 보는 사람별로 거른 것만 그린다. 보는 사람 선택은 인증이 아니다
// 고정 탭 "회의" - 목록 · 달력 · 할 일 보기. 정렬 · 나누기는 받은 것 안에서만 하는 화면 표시다
import { useEffect, useMemo, useState } from 'react'
import { fetchMeetings, fetchTasks, fetchWorkspaces, type Meeting, type Task, type TaskStatus, type Viewer, type WorkspaceOption } from './api'
import { LAYER_COLOR } from './colors'
import { MeetingForm, MEETING_STATUS_LABEL } from './MeetingForm'
import { errorText, personalName, TaskItem, WorkspaceBadge } from './MeetingPage'
import { formatRange, isOverdue, localToday, meetingsByDate, monthGrid, TASK_COLUMN_LABEL, taskColumns } from './meetingsView'

type Kind = 'list' | 'calendar' | 'tasks'
const KIND_LABEL: Record<Kind, string> = { list: '목록', calendar: '달력', tasks: '할 일' }
const WEEKDAYS = ['일', '월', '화', '수', '목', '금', '토']

export function MeetingsTab({
  viewer,
  version,
  onOpenMeeting,
}: {
  viewer: Viewer
  // 회의가 바뀌면 올라가는 값 - 바뀌면 다시 불러온다
  version: number
  onOpenMeeting: (meetingId: string) => void
}) {
  const [kind, setKind] = useState<Kind>('list')
  const [meetings, setMeetings] = useState<Meeting[] | null>(null)
  const [tasks, setTasks] = useState<Task[]>([])
  const [boardTasks, setBoardTasks] = useState<Task[]>([])
  const [spaces, setSpaces] = useState<WorkspaceOption[]>([])
  const [mine, setMine] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [creating, setCreating] = useState(false)
  const [selectedTask, setSelectedTask] = useState<string | null>(null)
  const [reloads, setReloads] = useState(0)
  const today = localToday()
  const [month, setMonth] = useState({ year: Number(today.slice(0, 4)), month: Number(today.slice(5, 7)) })
  const myName = personalName(viewer)
  const assignee = mine && myName ? myName : undefined

  useEffect(() => {
    let alive = true
    Promise.all([
      fetchMeetings(viewer.viewer_id),
      fetchTasks(viewer.viewer_id),
      fetchTasks(viewer.viewer_id, undefined, assignee),
      fetchWorkspaces(viewer.viewer_id),
    ])
      .then(([m, t, board, w]) => {
        if (!alive) return
        setMeetings(m)
        setTasks(t)
        setBoardTasks(board)
        setSpaces(w)
        setError(null)
      })
      .catch((e: unknown) => alive && setError(errorText(e)))
    return () => {
      alive = false
    }
  }, [viewer.viewer_id, assignee, version, reloads])

  const byDate = useMemo(() => meetingsByDate(meetings ?? []), [meetings])
  const columns = useMemo(() => taskColumns(boardTasks), [boardTasks])
  const taskCount = useMemo(() => {
    const counts = new Map<string, number>()
    for (const task of tasks) if (task.meeting_id) counts.set(task.meeting_id, (counts.get(task.meeting_id) ?? 0) + 1)
    return counts
  }, [tasks])

  if (error) return <div className="notice">{error}</div>
  if (!meetings) return <div className="notice">불러오는 중</div>

  const moveMonth = (delta: number) =>
    setMonth(({ year, month: m }) => {
      const index = year * 12 + (m - 1) + delta
      return { year: Math.floor(index / 12), month: (index % 12) + 1 }
    })

  const openTask = (task: Task) => {
    if (task.meeting_id) onOpenMeeting(task.meeting_id)
    else setSelectedTask(task.task_id)
  }
  const picked = tasks.find((task) => task.task_id === selectedTask) ?? null
  const membersOf = (task: Task) =>
    spaces.find((o) => o.workspace.layer === task.workspace.layer && o.workspace.group === task.workspace.group)?.members ?? []

  return (
    <div className="db meetings-tab">
      <div className="db-tabs">
        {(Object.keys(KIND_LABEL) as Kind[]).map((key) => (
          <button key={key} className={kind === key ? 'db-tab on' : 'db-tab'} onClick={() => setKind(key)}>
            {KIND_LABEL[key]}
          </button>
        ))}
        <span className="grow" />
        <button className="new-meeting" onClick={() => setCreating(true)}>
          새 회의
        </button>
      </div>
      {creating && (
        <MeetingForm
          viewerId={viewer.viewer_id}
          onCancel={() => setCreating(false)}
          onSaved={(saved) => {
            setCreating(false)
            setReloads((n) => n + 1)
            onOpenMeeting(saved.meeting_id)
          }}
        />
      )}
      {kind === 'list' && (
        <table className="db-table">
          <thead>
            <tr>
              {['제목', '일시', '워크스페이스', '참석자', '상태', '회의록', '할 일'].map((label) => (
                <th key={label}>{label}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {meetings.map((meeting) => (
              <tr key={meeting.meeting_id} onClick={() => onOpenMeeting(meeting.meeting_id)}>
                <td className="db-title">{meeting.title}</td>
                <td className="mono">{formatRange(meeting.starts_at, meeting.ends_at)}</td>
                <td>
                  <WorkspaceBadge workspace={meeting.workspace} />
                </td>
                <td>{meeting.attendees.length}</td>
                <td>{MEETING_STATUS_LABEL[meeting.status]}</td>
                <td>{meeting.minutes_doc_id ? '연결됨' : <span className="muted">없음</span>}</td>
                <td>{taskCount.get(meeting.meeting_id) ?? 0}</td>
              </tr>
            ))}
            {meetings.length === 0 && (
              <tr>
                <td colSpan={7} className="muted">
                  보이는 회의 없음
                </td>
              </tr>
            )}
          </tbody>
        </table>
      )}
      {kind === 'calendar' && (
        <div className="calendar">
          <div className="calendar-head">
            <button aria-label="이전 달" onClick={() => moveMonth(-1)}>
              ‹
            </button>
            <strong>
              {month.year}년 {month.month}월
            </strong>
            <button aria-label="다음 달" onClick={() => moveMonth(1)}>
              ›
            </button>
          </div>
          <div className="calendar-grid">
            {WEEKDAYS.map((day) => (
              <div key={day} className="calendar-weekday">
                {day}
              </div>
            ))}
            {monthGrid(month.year, month.month).map((cell) => (
              <div
                key={cell.date}
                className={['calendar-cell', cell.inMonth ? '' : 'outside', cell.date === today ? 'today' : ''].join(' ').trim()}
              >
                <span className="calendar-day">{Number(cell.date.slice(8))}</span>
                {(byDate.get(cell.date) ?? []).map((meeting) => (
                  <button
                    key={meeting.meeting_id}
                    className="calendar-chip"
                    title={formatRange(meeting.starts_at, meeting.ends_at)}
                    style={{ borderLeftColor: LAYER_COLOR[meeting.workspace.layer] }}
                    onClick={() => onOpenMeeting(meeting.meeting_id)}
                  >
                    {meeting.title}
                  </button>
                ))}
              </div>
            ))}
          </div>
        </div>
      )}
      {kind === 'tasks' && (
        <>
          {myName && (
            <label className="check mine-toggle">
              <input type="checkbox" checked={mine} onChange={(e) => setMine(e.target.checked)} />
              내 할 일만
            </label>
          )}
          <div className="board">
            {(Object.keys(columns) as TaskStatus[]).map((status) => (
              <div key={status} className="board-col">
                <div className="board-head">
                  {TASK_COLUMN_LABEL[status]} ( {columns[status].length} )
                </div>
                {columns[status].map((task) => (
                  <div key={task.task_id} className="board-card" onClick={() => openTask(task)}>
                    <div className="board-title">{task.title}</div>
                    <div className="board-meta">
                      <span>{task.assignee}</span>
                      <span className="sep">·</span>
                      <span>{task.due ?? '기한 없음'}</span>
                      {isOverdue(task, today) && <span className="badge overdue">기한 지남</span>}
                      <span className="sep">·</span>
                      <WorkspaceBadge workspace={task.workspace} />
                      <span className="sep">·</span>
                      <span className="muted">기록 {task.progress.length}</span>
                    </div>
                  </div>
                ))}
              </div>
            ))}
          </div>
          {picked && (
            <div className="task-panel">
              <button className="task-panel-close" onClick={() => setSelectedTask(null)}>
                닫기
              </button>
              <TaskItem task={picked} members={membersOf(picked)} viewer={viewer} onChanged={() => setReloads((n) => n + 1)} />
            </div>
          )}
        </>
      )}
    </div>
  )
}
