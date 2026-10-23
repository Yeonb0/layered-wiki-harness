// 사용자 결정 2026-10-23 ( 지침 v3.1 · 3절 27 ) : 할 일 배정은 회의록 승인 뒤 버튼으로 도는 별도 역할. 결과는 에이전트 제안으로 표시하고 사람이 확정 / 버린다. 확정 뒤 팀원이 진행 기록을 덧붙인다
// 규칙 검사는 서버가 하고 화면은 서버 message 를 그대로 보인다 - 남은 제안이 있어도 문서 확정 버튼을 미리 막지 않는다
import { useEffect, useState } from 'react'
import {
  addProgress, ApiError, confirmMeetingDoc, confirmTask, discardTask, fetchAssignStatus, fetchMeetingDocs, fetchProposals, fetchTasks,
  requestAssign, type AssignStatus, type Meeting, type MeetingDoc, type Task, type Viewer,
} from './api'
import { assignButtonState, droppedReasonLabel, groupByAssignee, problemLabel } from './assignView'
import { formatAt } from './meetingsView'
import { personalName } from './MeetingPage'
import { Toggle } from './Toggle'

function ProgressBox({ viewer, task, onChanged }: { viewer: Viewer; task: Task; onChanged: () => void }) {
  const [text, setText] = useState('')
  const [error, setError] = useState<string | null>(null)
  const add = async () => {
    setError(null)
    try {
      await addProgress(viewer.viewer_id, task.task_id, text)
      setText('')
      onChanged()
    } catch (e) {
      setError((e as Error).message)
    }
  }
  return (
    <>
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
        <form
          className="progress-add"
          onSubmit={(event) => {
            event.preventDefault()
            if (text.trim() !== '') void add()
          }}
        >
          <input placeholder="진행 상황 추가" value={text} onChange={(e) => setText(e.target.value)} />
          <button type="submit" disabled={text.trim() === ''}>
            추가
          </button>
        </form>
      ) : (
        <p className="muted">진행 기록은 개인 보는 사람으로 쓴다</p>
      )}
      {error && <div className="notice error">{error}</div>}
    </>
  )
}

function DocCard({
  viewer,
  meeting,
  doc,
  tasks,
  attendee,
  onChanged,
}: {
  viewer: Viewer
  meeting: Meeting
  doc: MeetingDoc
  tasks: Task[]
  attendee: boolean
  onChanged: () => void
}) {
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [docError, setDocError] = useState<string | null>(null)
  const act = async (key: string, run: () => Promise<unknown>) => {
    setErrors((prev) => ({ ...prev, [key]: '' }))
    try {
      await run()
      onChanged()
    } catch (e) {
      setErrors((prev) => ({ ...prev, [key]: (e as Error).message }))
    }
  }
  const confirmDoc = async () => {
    setDocError(null)
    try {
      await confirmMeetingDoc(viewer.viewer_id, doc.doc_id)
      onChanged()
    } catch (e) {
      setDocError((e as Error).message)
    }
  }
  const mine = tasks.filter((task) => doc.task_ids.includes(task.task_id))
  return (
    <div className="doc-card">
      <div className="doc-head">
        <strong>{meeting.title} · 회의 문서</strong>
        {doc.status === 'proposal' ? (
          <span className="badge agent">에이전트 제안</span>
        ) : (
          <span className="badge status-decided">
            확정 · {doc.confirmed_by} · {doc.confirmed_at ? formatAt(doc.confirmed_at) : ''}
          </span>
        )}
      </div>
      <h4>요약</h4>
      <p>{doc.summary}</p>
      <h4>결정 사항</h4>
      {doc.decisions.length === 0 ? (
        <p className="muted">없음</p>
      ) : (
        <ul>
          {doc.decisions.map((item, index) => (
            <li key={index}>{item}</li>
          ))}
        </ul>
      )}
      <h4>할 일</h4>
      {mine.length === 0 && <p className="muted">없음</p>}
      {groupByAssignee(mine, meeting.attendees).map((group) => (
        <div key={group.assignee} className="assignee-group">
          <h5>{group.assignee}</h5>
          {group.tasks.map((task) => (
            <div key={task.task_id} className="assign-task">
              <div className="task-head">
                <strong>{task.title}</strong>
                {task.source === 'agent_proposal' && <span className="badge agent">에이전트 제안</span>}
                {task.source === 'agent_confirmed' && <span className="badge agent">에이전트 제안 → 확정</span>}
                <span className="muted">{task.due ?? '기한 없음'}</span>
              </div>
              {task.evidence !== undefined && <blockquote className="evidence">회의록 : {task.evidence}</blockquote>}
              {task.source === 'agent_proposal' && attendee && (
                <div className="proposal-actions">
                  <button className="approve" onClick={() => void act(task.task_id, () => confirmTask(viewer.viewer_id, task.task_id))}>
                    확정
                  </button>
                  <button className="reject" onClick={() => void act(task.task_id, () => discardTask(viewer.viewer_id, task.task_id))}>
                    버리기
                  </button>
                </div>
              )}
              {task.source === 'agent_confirmed' && <ProgressBox viewer={viewer} task={task} onChanged={onChanged} />}
              {errors[task.task_id] && <div className="notice error">{errors[task.task_id]}</div>}
            </div>
          ))}
        </div>
      ))}
      {attendee && doc.status === 'proposal' && (
        <div className="doc-actions">
          <button onClick={() => void confirmDoc()}>문서 확정</button>
        </div>
      )}
      {docError && <div className="notice error">{docError}</div>}
    </div>
  )
}

export function AssignPanel({
  viewer,
  meeting,
  minutesVersion,
  onTasksChanged,
}: {
  viewer: Viewer
  meeting: Meeting
  // 회의록 doc 상태가 바뀌면 올라간다 - 바뀌면 상태 · 문서 · 배정 상태를 다시 불러온다
  minutesVersion: number
  // 할 일이 바뀌면 회의 상세의 할 일 토글을 다시 불러오게 알린다
  onTasksChanged: () => void
}) {
  const [decided, setDecided] = useState<boolean | null>(null)
  const [docs, setDocs] = useState<MeetingDoc[]>([])
  const [tasks, setTasks] = useState<Task[]>([])
  const [assign, setAssign] = useState<AssignStatus | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [requestError, setRequestError] = useState<string | null>(null)
  const [tick, setTick] = useState(0)
  const myName = personalName(viewer)
  const attendee = myName !== null && meeting.attendees.includes(myName)
  const personal = meeting.workspace.layer === '개인'
  const buttonState = assignButtonState(docs)

  useEffect(() => {
    if (personal) return
    let alive = true
    let timer: ReturnType<typeof setTimeout> | undefined
    Promise.all([
      fetchProposals(viewer.viewer_id),
      fetchMeetingDocs(viewer.viewer_id, meeting.meeting_id),
      fetchTasks(viewer.viewer_id, meeting.meeting_id),
      // 배정 작업이 아직 없으면 404 다
      fetchAssignStatus(viewer.viewer_id, meeting.meeting_id).catch((e: unknown) => {
        if (e instanceof ApiError && e.status === 404) return null
        throw e
      }),
    ])
      .then(([proposals, loadedDocs, loadedTasks, status]) => {
        if (!alive) return
        setDecided(proposals.some((p) => p.doc_id === meeting.minutes_doc_id && p.status === 'decided'))
        setDocs(loadedDocs)
        setTasks(loadedTasks)
        setAssign((previous) => {
          // 돌던 배정이 끝났으면 할 일 토글도 새로 불러온다
          if (previous?.status === 'running' && status?.status !== 'running') onTasksChanged()
          return status
        })
        setError(null)
        if (status?.status === 'running') timer = setTimeout(() => setTick((t) => t + 1), 2000)
      })
      .catch((e: unknown) => alive && setError((e as Error).message))
    return () => {
      alive = false
      if (timer !== undefined) clearTimeout(timer)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [viewer.viewer_id, meeting.meeting_id, meeting.minutes_doc_id, tick, personal, minutesVersion])

  const request = async () => {
    setRequestError(null)
    try {
      await requestAssign(viewer.viewer_id, meeting.meeting_id)
      setTick((t) => t + 1)
    } catch (e) {
      setRequestError((e as Error).message)
    }
  }
  const changed = () => {
    setTick((t) => t + 1)
    onTasksChanged()
  }

  return (
    <Toggle title="할 일 제안 · 회의 문서">
      {personal ? (
        <p className="muted">개인 일정에는 회의록을 투입하지 않는다</p>
      ) : (
        <>
          {error && <div className="notice error">{error}</div>}
          {decided === false && <p className="muted">회의록 승인이 끝나면 할 일 제안을 받을 수 있다</p>}
          {decided === true && (
            <>
              {attendee ? (
                buttonState !== 'hidden' && (
                  <>
                    <button disabled={assign?.status === 'running'} onClick={() => void request()}>
                      {buttonState === 'again' ? '할 일 제안 다시 받기' : '할 일 제안 받기'}
                    </button>
                    {buttonState === 'again' && <p className="muted">새 회의 문서가 하나 더 만들어진다</p>}
                  </>
                )
              ) : (
                <p className="muted">회의 참석자 ( 개인 보는 사람 ) 만 할 일 제안을 요청한다</p>
              )}
              {requestError && <div className="notice error">{requestError}</div>}
              {assign?.status === 'running' && <p className="muted">에이전트가 할 일을 정리하는 중이다 ( 2초마다 갱신 )</p>}
              {assign?.status === 'failed' && <div className="notice error">배정 실패 : {assign.error}</div>}
              {assign && assign.status !== 'running' && (
                <>
                  {assign.dropped.length > 0 && (
                    <div className="notice warn">
                      <strong>빠진 제안 {assign.tasks_dropped}개</strong>
                      <ul>
                        {assign.dropped.map((item, index) => (
                          <li key={index}>
                            {item.title ?? '( 제목 없음 )'} - {droppedReasonLabel(item.reason)}
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                  {assign.problems.length > 0 && (
                    <div className="notice warn">
                      <strong>고친 것</strong>
                      <ul>
                        {assign.problems.map((item, index) => (
                          <li key={index}>
                            {item.task_title} - {problemLabel(item.problem)} ( 제안 : {item.given} )
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                </>
              )}
              {docs.map((doc) => (
                <DocCard key={doc.doc_id} viewer={viewer} meeting={meeting} doc={doc} tasks={tasks} attendee={attendee} onChanged={changed} />
              ))}
            </>
          )}
        </>
      )}
    </Toggle>
  )
}
