// 사용자 결정 2026-10-23 ( 지침 v3.1 ) : 시연 경로 회의 기능. 회의 · 할 일은 서버가 보는 사람별로 거른 것만 그린다. 보는 사람 선택은 인증이 아니다
// 사용자 요청 2026-10-23 : 회의 화면 다듬기 ( 간격 · 일시 형식 · Enter 저장 · 기한 지남 · 노트 0개 안내 )
// 회의 상세 탭 - 노션 페이지처럼 제목 · 속성 블록 · 토글. 노트 목록은 지금 보기 ( 서버가 거른 것 ) 안에서만 고른다
import { useCallback, useEffect, useState } from 'react'
import {
  addProgress, ApiError, createTask, fetchMeeting, fetchTasks, fetchWorkspaces, updateTask, type Meeting, type Task, type TaskStatus,
  type ViewResponse, type Viewer, type Workspace,
} from './api'
import { LAYER_COLOR } from './colors'
import { MeetingForm, MEETING_STATUS_LABEL } from './MeetingForm'
import { formatAt, formatRange, isOverdue, localToday, workspaceLabel } from './meetingsView'
import { Toggle } from './Toggle'

const TASK_STATUS_LABEL: Record<TaskStatus, string> = { todo: '할 일', doing: '진행 중', done: '완료' }
export const MEETINGS_OFF = '시연 API 를 --meetings-file 로 띄우면 보인다'

export function errorText(error: unknown): string {
  // 503 ( MeetingsNotConfigured ) 은 서버 문구 대신 화면 안내를 보인다
  return error instanceof ApiError && error.status === 503 ? MEETINGS_OFF : (error as Error).message
}

export function WorkspaceBadge({ workspace }: { workspace: Workspace }) {
  return (
    <span className="badge" style={{ background: LAYER_COLOR[workspace.layer] }}>
      {workspaceLabel(workspace)}
    </span>
  )
}

// 개인 보는 사람의 표시 이름 - viewer_id 는 "개인:이름" 이다
export function personalName(viewer: Viewer): string | null {
  return viewer.layer === '개인' ? viewer.viewer_id.slice('개인:'.length) : null
}

export function TaskItem({
  task,
  members,
  viewer,
  onChanged,
}: {
  task: Task
  members: string[]
  viewer: Viewer
  onChanged: () => void
}) {
  const [error, setError] = useState<string | null>(null)
  const [text, setText] = useState('')
  const [progressError, setProgressError] = useState<string | null>(null)
  const today = localToday()
  const change = async (fields: Partial<Pick<Task, 'assignee' | 'due' | 'status'>>) => {
    setError(null)
    try {
      await updateTask(viewer.viewer_id, task.task_id, fields)
      onChanged()
    } catch (e) {
      setError(errorText(e))
    }
  }
  const addNote = async () => {
    setProgressError(null)
    try {
      await addProgress(viewer.viewer_id, task.task_id, text)
      // 저장에 성공했을 때만 입력칸을 비운다
      setText('')
      onChanged()
    } catch (e) {
      setProgressError(errorText(e))
    }
  }
  return (
    <div className="task-item">
      <div className="task-head">
        <strong>{task.title}</strong>
        <WorkspaceBadge workspace={task.workspace} />
        {task.source === 'agent_proposal' && <span className="badge agent">에이전트 제안</span>}
        {task.source === 'agent_confirmed' && <span className="badge agent">에이전트 제안 → 확정</span>}
      </div>
      {error && <div className="notice error">{error}</div>}
      <div className="task-props">
        <label>
          상태
          <select value={task.status} onChange={(e) => void change({ status: e.target.value as TaskStatus })}>
            {(Object.keys(TASK_STATUS_LABEL) as TaskStatus[]).map((key) => (
              <option key={key} value={key}>
                {TASK_STATUS_LABEL[key]}
              </option>
            ))}
          </select>
        </label>
        <label>
          담당자
          <select value={task.assignee} onChange={(e) => void change({ assignee: e.target.value })}>
            {(members.includes(task.assignee) ? members : [task.assignee, ...members]).map((name) => (
              <option key={name} value={name}>
                {name}
              </option>
            ))}
          </select>
        </label>
        <label>
          기한
          <input type="date" value={task.due ?? ''} onChange={(e) => void change({ due: e.target.value === '' ? null : e.target.value })} />
        </label>
        {isOverdue(task, today) && <span className="badge overdue">기한 지남</span>}
      </div>
      <ul className="progress-list">
        {task.progress.length === 0 && <li className="muted">진행 기록 없음</li>}
        {task.progress.map((entry, index) => (
          <li key={index}>
            <span className="muted">
              {entry.author} · {formatAt(entry.at)}
            </span>{' '}
            {entry.text}
          </li>
        ))}
      </ul>
      {viewer.layer === '개인' ? (
        <>
          <form
            className="progress-add"
            onSubmit={(event) => {
              event.preventDefault()
              if (text.trim() !== '') void addNote()
            }}
          >
            <input placeholder="진행 상황 추가" value={text} onChange={(e) => setText(e.target.value)} />
            <button type="submit" disabled={text.trim() === ''}>
              추가
            </button>
          </form>
          {progressError && <div className="notice error">{progressError}</div>}
        </>
      ) : (
        <p className="muted">진행 기록은 개인 보는 사람으로 쓴다</p>
      )}
    </div>
  )
}

export function MeetingPage({
  viewer,
  meetingId,
  view,
  onOpenNote,
  onChanged,
  onOtherMode,
}: {
  viewer: Viewer
  meetingId: string
  // 지금 보기 ( 서버가 거른 노트 ) - 아직 못 받았으면 null
  view: ViewResponse | null
  onOpenNote: (noteId: string) => void
  // 회의가 바뀌면 탭 제목 · 목록을 다시 불러오게 알린다
  onChanged: () => void
  // Workspace 의 모드를 바꾼다 - 회의 탭은 그대로 둔다
  onOtherMode: () => void
}) {
  const [meeting, setMeeting] = useState<Meeting | null>(null)
  const [tasks, setTasks] = useState<Task[]>([])
  const [members, setMembers] = useState<string[]>([])
  const [error, setError] = useState<string | null>(null)
  const [editing, setEditing] = useState(false)
  const [version, setVersion] = useState(0)
  const reload = useCallback(() => setVersion((v) => v + 1), [])

  useEffect(() => {
    let alive = true
    Promise.all([fetchMeeting(viewer.viewer_id, meetingId), fetchTasks(viewer.viewer_id, meetingId), fetchWorkspaces(viewer.viewer_id)])
      .then(([m, t, spaces]) => {
        if (!alive) return
        setMeeting(m)
        setTasks(t)
        setMembers(spaces.find((o) => o.workspace.layer === m.workspace.layer && o.workspace.group === m.workspace.group)?.members ?? [])
        setError(null)
      })
      .catch((e: unknown) => alive && setError(errorText(e)))
    return () => {
      alive = false
    }
  }, [viewer.viewer_id, meetingId, version])

  if (error) return <div className="notice error">{error}</div>
  if (!meeting) return <div className="notice">불러오는 중</div>

  const minutesNotes = meeting.minutes_doc_id && view ? view.notes.filter((n) => n.source_doc_id === meeting.minutes_doc_id) : []
  const layers = ['전사', '팀', '개인'].filter((layer) => minutesNotes.some((n) => n.layer === layer))

  return (
    <div className="meeting-page">
      <h1>{meeting.title}</h1>
      <dl className="props">
        <dt>일시</dt>
        <dd>
          {formatRange(meeting.starts_at, meeting.ends_at)}
        </dd>
        <dt>워크스페이스</dt>
        <dd>
          <WorkspaceBadge workspace={meeting.workspace} />
        </dd>
        <dt>참석자</dt>
        <dd>
          {meeting.attendees.length === 0 && <span className="muted">없음</span>}
          {meeting.attendees.map((name) => (
            <span key={name} className="chip">
              {name}
            </span>
          ))}
        </dd>
        <dt>상태</dt>
        <dd>{MEETING_STATUS_LABEL[meeting.status]}</dd>
      </dl>
      {editing ? (
        <MeetingForm
          viewerId={viewer.viewer_id}
          meeting={meeting}
          onCancel={() => setEditing(false)}
          onSaved={() => {
            setEditing(false)
            reload()
            onChanged()
          }}
        />
      ) : (
        <button onClick={() => setEditing(true)}>고치기</button>
      )}
      <Toggle title="안건">
        {meeting.agenda.length === 0 ? (
          <p className="muted">없음</p>
        ) : (
          <ul>
            {meeting.agenda.map((item, index) => (
              <li key={index}>{item}</li>
            ))}
          </ul>
        )}
      </Toggle>
      <Toggle title="회의록에서 나온 노트">
        {!meeting.minutes_doc_id ? (
          <p className="muted">연결된 회의록 없음</p>
        ) : (
          <>
            <p className="muted">이 보는 사람에게 보이는 노트 {minutesNotes.length}개 ( 서버가 거른 보기 기준 )</p>
            {view && minutesNotes.length === 0 && (
              <>
                <p className="muted">이 모드의 보기에는 이 회의록에서 나온 노트가 없다 ( 배치되지 않았거나 이 보는 사람에게 보이지 않는 층일 수 있다 )</p>
                <button onClick={onOtherMode}>다른 모드에서 보기</button>
              </>
            )}
            {layers.map((layer) => (
              <div key={layer}>
                <h4 style={{ color: LAYER_COLOR[layer] }}>{layer}</h4>
                <ul className="links">
                  {minutesNotes
                    .filter((n) => n.layer === layer)
                    .map((n) => (
                      <li key={n.note_id}>
                        <button className="link" onClick={() => onOpenNote(n.note_id)}>
                          {n.title}
                        </button>
                      </li>
                    ))}
                </ul>
              </div>
            ))}
          </>
        )}
      </Toggle>
      <Toggle title="할 일">
        {tasks.length === 0 && <p className="muted">없음</p>}
        {tasks.map((task) => (
          <TaskItem key={task.task_id} task={task} members={members} viewer={viewer} onChanged={reload} />
        ))}
        <NewTask viewerId={viewer.viewer_id} meetingId={meeting.meeting_id} members={members} onCreated={reload} />
      </Toggle>
    </div>
  )
}

function NewTask({ viewerId, meetingId, members, onCreated }: { viewerId: string; meetingId: string; members: string[]; onCreated: () => void }) {
  const [title, setTitle] = useState('')
  const [assignee, setAssignee] = useState('')
  const [due, setDue] = useState('')
  const [error, setError] = useState<string | null>(null)
  const who = assignee || members[0] || ''
  const add = async () => {
    setError(null)
    try {
      await createTask(viewerId, { title, assignee: who, due: due === '' ? null : due, meeting_id: meetingId })
      setTitle('')
      setDue('')
      onCreated()
    } catch (e) {
      setError(errorText(e))
    }
  }
  return (
    <div className="new-task">
      <h4>할 일 추가</h4>
      {error && <div className="notice error">{error}</div>}
      <div className="task-props">
        <input placeholder="제목" value={title} onChange={(e) => setTitle(e.target.value)} />
        <select value={who} onChange={(e) => setAssignee(e.target.value)}>
          {members.map((name) => (
            <option key={name} value={name}>
              {name}
            </option>
          ))}
        </select>
        <input type="date" value={due} onChange={(e) => setDue(e.target.value)} />
        <button disabled={title.trim() === '' || who === ''} onClick={() => void add()}>
          추가
        </button>
      </div>
    </div>
  )
}
