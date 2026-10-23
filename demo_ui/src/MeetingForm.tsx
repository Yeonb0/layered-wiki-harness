// 사용자 결정 2026-10-23 ( 지침 v3.1 ) : 시연 경로 회의 기능. 회의 · 할 일은 서버가 보는 사람별로 거른 것만 그린다. 보는 사람 선택은 인증이 아니다
// 만들기 · 고치기 공용 폼 - 규칙 검사는 서버가 하고 화면은 서버 400 의 message 를 그대로 보인다 ( 비어 있는 제목 정도의 입력 형태만 막는다 )
import { useEffect, useState } from 'react'
import { createMeeting, fetchWorkspaces, updateMeeting, type Meeting, type MeetingStatus, type WorkspaceOption } from './api'

const STATUS_LABEL: Record<MeetingStatus, string> = { scheduled: '예정', done: '완료', cancelled: '취소' }
export { STATUS_LABEL as MEETING_STATUS_LABEL }

export function MeetingForm({
  viewerId,
  meeting,
  onSaved,
  onCancel,
}: {
  viewerId: string
  // 있으면 고치기, 없으면 만들기
  meeting?: Meeting
  onSaved: (saved: Meeting) => void
  onCancel: () => void
}) {
  const [options, setOptions] = useState<WorkspaceOption[] | null>(null)
  const [title, setTitle] = useState(meeting?.title ?? '')
  const [startsAt, setStartsAt] = useState(meeting?.starts_at ?? '')
  const [endsAt, setEndsAt] = useState(meeting?.ends_at ?? '')
  const [label, setLabel] = useState<string | null>(null)
  const [attendees, setAttendees] = useState<string[]>(meeting?.attendees ?? [])
  const [agenda, setAgenda] = useState((meeting?.agenda ?? []).join('\n'))
  const [status, setStatus] = useState<MeetingStatus>(meeting?.status ?? 'scheduled')
  const [minutes, setMinutes] = useState(meeting?.minutes_doc_id ?? '')
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    let alive = true
    fetchWorkspaces(viewerId)
      .then((list) => {
        if (!alive) return
        setOptions(list)
        const own = meeting && list.find((o) => o.workspace.layer === meeting.workspace.layer && o.workspace.group === meeting.workspace.group)
        setLabel((own ?? list[0])?.label ?? null)
      })
      .catch((e: Error) => alive && setError(e.message))
    return () => {
      alive = false
    }
  }, [viewerId, meeting])

  const chosen = options?.find((o) => o.label === label) ?? null

  const pickWorkspace = (next: string) => {
    setLabel(next)
    // 다른 워크스페이스의 구성원이 아닌 참석자는 체크에서 빠진다 - 남기는 것은 화면의 편의일 뿐 규칙 판정은 서버가 한다
    const members = options?.find((o) => o.label === next)?.members ?? []
    setAttendees((current) => current.filter((name) => members.includes(name)))
  }

  const toggleAttendee = (name: string) =>
    setAttendees((current) => (current.includes(name) ? current.filter((n) => n !== name) : [...current, name]))

  const save = async () => {
    if (!title.trim()) {
      setError('제목을 입력한다')
      return
    }
    if (!chosen) return
    setSaving(true)
    setError(null)
    const fields = {
      title,
      starts_at: startsAt,
      ends_at: endsAt,
      workspace: chosen.workspace,
      attendees,
      agenda: agenda.split('\n').map((line) => line.trim()).filter((line) => line !== ''),
    }
    try {
      const saved = meeting
        ? await updateMeeting(viewerId, meeting.meeting_id, { ...fields, status, minutes_doc_id: minutes.trim() === '' ? null : minutes.trim() })
        : await createMeeting(viewerId, fields)
      onSaved(saved)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <form
      className="meeting-form"
      onSubmit={(event) => {
        event.preventDefault()
        void save()
      }}
    >
      <h3>{meeting ? '회의 고치기' : '새 회의'}</h3>
      {error && <div className="notice error">{error}</div>}
      <label>
        제목
        <input value={title} onChange={(e) => setTitle(e.target.value)} />
      </label>
      <div className="form-row">
        <label>
          시작
          <input type="datetime-local" value={startsAt} onChange={(e) => setStartsAt(e.target.value)} />
        </label>
        <label>
          끝
          <input type="datetime-local" value={endsAt} onChange={(e) => setEndsAt(e.target.value)} />
        </label>
      </div>
      <label>
        워크스페이스
        <select value={label ?? ''} onChange={(e) => pickWorkspace(e.target.value)} disabled={!options}>
          {(options ?? []).map((o) => (
            <option key={o.label} value={o.label}>
              {o.label}
            </option>
          ))}
        </select>
      </label>
      <fieldset>
        <legend>참석자</legend>
        {(chosen?.members ?? []).map((name) => (
          <label key={name} className="check">
            <input type="checkbox" checked={attendees.includes(name)} onChange={() => toggleAttendee(name)} />
            {name}
          </label>
        ))}
      </fieldset>
      <label>
        안건 ( 줄마다 하나 )
        <textarea rows={4} value={agenda} onChange={(e) => setAgenda(e.target.value)} />
      </label>
      {meeting && (
        <>
          <label>
            상태
            <select value={status} onChange={(e) => setStatus(e.target.value as MeetingStatus)}>
              {(Object.keys(STATUS_LABEL) as MeetingStatus[]).map((key) => (
                <option key={key} value={key}>
                  {STATUS_LABEL[key]}
                </option>
              ))}
            </select>
          </label>
          <label>
            회의록 문서 id ( 선택 )
            <input value={minutes} onChange={(e) => setMinutes(e.target.value)} />
          </label>
        </>
      )}
      <div className="form-actions">
        <button type="submit" disabled={saving || !chosen}>
          저장
        </button>
        <button type="button" onClick={onCancel}>
          취소
        </button>
      </div>
    </form>
  )
}
