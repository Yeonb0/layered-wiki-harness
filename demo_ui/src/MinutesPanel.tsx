// 사용자 결정 2026-10-23 ( 지침 v3.1 ) : 회의록 투입 ( 차수 901 ) → 에이전트 분해 · 배치 → 참석자가 노트별 승인 / 반려 → 승인된 노트만 볼트에 겹친다. 승인 게이트는 승격이 아니다
// 규칙 검사는 서버가 하고 화면은 서버 message 를 그대로 보인다 - 글자 수 상한도 서버가 판정한다
import { useEffect, useRef, useState } from 'react'
import {
  decideProposal, fetchProposal, fetchProposals, submitMinutes, type Meeting, type Mode, type Proposal, type ProposalNote, type Viewer,
} from './api'
import { LAYER_COLOR } from './colors'
import { formatAt } from './meetingsView'
import { canApprove, proposalCounts, statusLabel } from './minutesView'
import { MODE_LABEL } from './Sidebar'
import { Toggle } from './Toggle'

const TEXT_LIMIT = 20000

function NoteCard({ note, onDecide, error }: { note: ProposalNote; onDecide: (decision: 'approve' | 'reject') => void; error: string | null }) {
  const [open, setOpen] = useState(false)
  return (
    <div className="proposal-card">
      <div className="proposal-head">
        <strong>{note.title ?? '( 제목 없음 )'}</strong>
        {note.layer !== null ? (
          <span className="badge" style={{ background: LAYER_COLOR[note.layer] }}>
            {note.layer}
          </span>
        ) : (
          <span className="badge failed">배치 실패</span>
        )}
        {note.group_label && <span className="muted">{note.group_label}</span>}
      </div>
      <p className="muted">
        출처 세그먼트 {note.source_segment_ids.length} · 상향 링크 {note.upward_links.length} · 하향 링크 {note.downward_links.length}
        {note.hidden_links > 0 && ` · 보이지 않는 링크 ${note.hidden_links}`}
      </p>
      {note.problems.length > 0 && <p className="notice warn">{note.problems.join(' / ')}</p>}
      {note.body !== null && (
        <>
          <button className="link" onClick={() => setOpen((value) => !value)}>
            {open ? '본문 접기' : '본문 보기'}
          </button>
          {open && <pre className="proposal-body">{note.body}</pre>}
        </>
      )}
      {note.decision !== null ? (
        <p className={note.decision.decision === 'approve' ? 'decision approved' : 'decision rejected'}>
          {note.decision.decision === 'approve' ? '승인' : '반려'} · {note.decision.by} · {formatAt(note.decision.at)}
        </p>
      ) : (
        <div className="proposal-actions">
          <span className="muted">미결</span>
          {canApprove(note) && (
            <button className="approve" onClick={() => onDecide('approve')}>
              승인
            </button>
          )}
          <button className="reject" onClick={() => onDecide('reject')}>
            반려
          </button>
        </div>
      )}
      {error && <div className="notice error">{error}</div>}
    </div>
  )
}

export function MinutesPanel({
  viewer,
  meeting,
  defaultMode,
  onReloadMeeting,
  onViewInVault,
  onChanged,
}: {
  viewer: Viewer
  meeting: Meeting
  defaultMode: Mode
  onReloadMeeting: () => void
  // 그 모드로 바꾸고 보기를 다시 불러온다
  onViewInVault: (mode: Mode) => void
  // doc 상태가 바뀌면 ( 투입 · 처리 끝 · 승인 / 반려 · decided ) 올린다 - 회의록 승인이 끝나면 탭을 다시 열지 않아도 할 일 제안 버튼이 나오게
  onChanged: () => void
}) {
  const [detail, setDetail] = useState<Proposal | null>(null)
  const [status, setStatus] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [text, setText] = useState('')
  const [mode, setMode] = useState<Mode>(defaultMode)
  const [submitError, setSubmitError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [tick, setTick] = useState(0)
  const [cardErrors, setCardErrors] = useState<Record<number, string>>({})
  // 처음 불러온 값은 변화가 아니다
  const lastStatus = useRef<string | null | undefined>(undefined)
  const linkedId = meeting.minutes_doc_id
  const personal = meeting.workspace.layer === '개인'

  useEffect(() => {
    if (personal) return
    let alive = true
    let timer: ReturnType<typeof setTimeout> | undefined
    fetchProposals(viewer.viewer_id)
      .then(async (all) => {
        const mine = all.filter((p) => p.meeting_id === meeting.meeting_id)
        const linked = mine.find((p) => p.doc_id === linkedId) ?? null
        // 연결이 풀린 투입 칸에는 가장 최근에 실패한 doc 의 원인을 보인다
        const target = linked ?? (linkedId === null ? [...mine].reverse().find((p) => p.status === 'failed') ?? null : null)
        const loaded = target && target.status !== 'running' ? await fetchProposal(viewer.viewer_id, target.doc_id) : null
        if (!alive) return
        setStatus(target?.status ?? null)
        if (lastStatus.current !== undefined && lastStatus.current !== (target?.status ?? null)) onChanged()
        lastStatus.current = target?.status ?? null
        setDetail(loaded)
        setError(null)
        if (linked?.status === 'running') timer = setTimeout(() => setTick((t) => t + 1), 3000)
        // 실패하면 서버가 회의 연결을 풀어 두었다 - 회의를 다시 불러와 투입 칸을 보인다
        if (linked?.status === 'failed') onReloadMeeting()
      })
      .catch((e: unknown) => alive && setError((e as Error).message))
    return () => {
      alive = false
      if (timer !== undefined) clearTimeout(timer)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [viewer.viewer_id, meeting.meeting_id, linkedId, tick, personal])

  const submit = async () => {
    setSubmitting(true)
    setSubmitError(null)
    try {
      await submitMinutes(viewer.viewer_id, meeting.meeting_id, mode, text)
      setText('')
      onReloadMeeting()
      onChanged()
    } catch (e) {
      setSubmitError((e as Error).message)
    } finally {
      setSubmitting(false)
    }
  }

  const decide = async (noteIndex: number, decision: 'approve' | 'reject') => {
    if (!detail) return
    setCardErrors((prev) => ({ ...prev, [noteIndex]: '' }))
    try {
      await decideProposal(viewer.viewer_id, detail.doc_id, [{ note_index: noteIndex, decision }])
      setTick((t) => t + 1)
      onChanged()
    } catch (e) {
      setCardErrors((prev) => ({ ...prev, [noteIndex]: (e as Error).message }))
    }
  }

  const counts = detail ? proposalCounts(detail) : null
  return (
    <Toggle title="회의록 투입 · 승인">
      {personal ? (
        <p className="muted">개인 일정에는 회의록을 투입하지 않는다</p>
      ) : (
        <>
          {error && <div className="notice error">{error}</div>}
          {linkedId === null ? (
            <>
              {detail && status === 'failed' && (
                <div className="notice error">
                  <span className="badge failed">{statusLabel('failed')}</span> 이전 투입 : {detail.error ?? '원인 없음'}
                </div>
              )}
              <div className="minutes-form">
                <textarea
                  rows={8}
                  placeholder="회의록 ( 마크다운 )"
                  value={text}
                  onChange={(e) => setText(e.target.value)}
                />
                <p className="muted">
                  {text.length} / {TEXT_LIMIT}자 ( 상한 {TEXT_LIMIT}자 )
                </p>
                <label>
                  모드
                  <select value={mode} onChange={(e) => setMode(e.target.value as Mode)}>
                    {(Object.keys(MODE_LABEL) as Mode[]).map((key) => (
                      <option key={key} value={key}>
                        {MODE_LABEL[key]}
                      </option>
                    ))}
                  </select>
                </label>
                {submitError && <div className="notice error">{submitError}</div>}
                <button disabled={submitting || text.trim() === ''} onClick={() => void submit()}>
                  회의록 투입
                </button>
              </div>
            </>
          ) : (
            <>
              <p>
                {status !== null && <span className={`badge status-${status}`}>{statusLabel(status)}</span>}
                {counts && ` 승인 ${counts.approved} · 반려 ${counts.rejected} · 미결 ${counts.pending}`}
              </p>
              {status === 'running' && <p className="muted">에이전트가 분해 · 배치하는 중이다 ( 3초마다 갱신 )</p>}
              {detail && (status === 'awaiting_approval' || status === 'decided') && (
                <>
                  <p className="notice warn">에이전트가 정한 층 그대로 승인 또는 반려한다. 층을 바꾸지 않는다 ( 승격 아님 )</p>
                  {detail.notes.map((note) => (
                    <NoteCard
                      key={note.note_index}
                      note={note}
                      error={cardErrors[note.note_index] || null}
                      onDecide={(decision) => void decide(note.note_index, decision)}
                    />
                  ))}
                  {status === 'decided' && (
                    <div className="notice">
                      <p>
                        승인된 노트 {detail.approved}개가 [ {MODE_LABEL[detail.mode]} ] 보기에 들어갔다
                      </p>
                      <button onClick={() => onViewInVault(detail.mode)}>볼트에서 보기</button>
                    </div>
                  )}
                </>
              )}
            </>
          )}
        </>
      )}
    </Toggle>
  )
}
