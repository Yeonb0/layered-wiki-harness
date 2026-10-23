// 사용자 결정 2026-10-23 : 라이브 1건 = 두 팀 소속 개인 페이지 ( 누출이 모드에 따라 갈리는 장면 ). 문서는 미리 돌린 실행의 20건 중 하나를 그 자리에서 다시 처리한다
// 사용자 결정 2026-10-23 : 라이브 투입은 화면 → 시연 API → Dify 워크플로 → 시연 API /jobs. Dify 앱 키는 서버만 가진다
import { useEffect, useState } from 'react'
import {
  fetchDocs, fetchJob, fetchLive, postLive, type DocItem, type JobStatus, type LiveState, type Mode,
} from './api'
import { LAYER_COLOR } from './colors'
import { MODE_LABEL } from './Sidebar'

export const LIVE_DEFAULT_DOC_ID = '90000000000000000000000000000015'
// 단계 표시를 새로 불러오는 간격
const POLL_MS = 3000

function docLabel(doc: DocItem): string {
  return `${doc.doc_id.slice(-4)} · ${doc.layer} · 세그먼트 ${doc.segments} · ${doc.chars}자`
}

type StepState = 'done' | 'active' | 'todo' | 'fail'

function Step({ state, label, detail }: { state: StepState; label: string; detail?: string }) {
  return (
    <li className={`step step-${state}`}>
      <span className="step-label">{label}</span>
      {detail && <span className="step-detail">{detail}</span>}
    </li>
  )
}

export function LiveTab({
  defaultMode,
  onOverlay,
}: {
  defaultMode: Mode
  onOverlay: (mode: Mode, jobId: string) => void
}) {
  const [docs, setDocs] = useState<DocItem[] | null>(null)
  const [docId, setDocId] = useState('')
  const [mode, setMode] = useState<Mode>(defaultMode)
  const [live, setLive] = useState<LiveState | null>(null)
  const [job, setJob] = useState<JobStatus | null>(null)
  const [error, setError] = useState<string | null>(null)

  // 처음 열 때 문서 목록과 지금 라이브 상태를 받는다 - 탭을 떠났다 와도 GET /live 로 상태를 다시 그린다
  useEffect(() => {
    let cancelled = false
    fetchDocs()
      .then((list) => {
        if (cancelled) return
        setDocs(list)
        // 기본 문서가 목록에 없으면 기본 선택 없이 안내 문구를 보인다
        if (list.some((d) => d.doc_id === LIVE_DEFAULT_DOC_ID)) setDocId(LIVE_DEFAULT_DOC_ID)
      })
      .catch((e: unknown) => !cancelled && setError(e instanceof Error ? e.message : String(e)))
    fetchLive()
      .then((state) => !cancelled && setLive(state))
      .catch((e: unknown) => !cancelled && setError(e instanceof Error ? e.message : String(e)))
    return () => {
      cancelled = true
    }
  }, [])

  const running = live?.status === 'running'
  useEffect(() => {
    if (!running) return
    const timer = setInterval(() => {
      fetchLive()
        .then(setLive)
        .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)))
    }, POLL_MS)
    return () => clearInterval(timer)
  }, [running])

  const jobId = live && live.status !== 'idle' ? live.job_id : null
  const liveDone = live !== null && live.status !== 'idle' && live.status !== 'running'
  useEffect(() => {
    if (!jobId || !liveDone) {
      setJob(null)
      return
    }
    let cancelled = false
    fetchJob(jobId)
      .then((status) => !cancelled && setJob(status))
      .catch((e: unknown) => !cancelled && setError(e instanceof Error ? e.message : String(e)))
    return () => {
      cancelled = true
    }
  }, [jobId, liveDone])

  const start = async () => {
    setError(null)
    setJob(null)
    try {
      await postLive(docId, mode)
      setLive(await fetchLive())
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  const record = live && live.status !== 'idle' ? live : null
  const step3: StepState = !record ? 'todo' : record.status === 'completed' ? 'done' : record.status === 'failed' ? 'fail' : 'todo'
  const result = job?.result && 'notes' in job.result ? job.result : null
  return (
    <div className="live">
      <h1>라이브 투입</h1>
      <p className="notice warn">링크는 에이전트가 이번 처리에서 만든 것만 그린다. 합성 문서는 링크가 나오도록 설계했다 ( 지침 3절 20 )</p>
      <div className="live-form">
        <label>
          문서{' '}
          <select value={docId} onChange={(e) => setDocId(e.target.value)} disabled={running}>
            <option value="">선택 안 함</option>
            {docs?.map((doc) => (
              <option key={doc.doc_id} value={doc.doc_id}>
                {docLabel(doc)}
              </option>
            ))}
          </select>
        </label>
        <label>
          모드{' '}
          <select value={mode} onChange={(e) => setMode(e.target.value as Mode)} disabled={running}>
            {(Object.keys(MODE_LABEL) as Mode[]).map((m) => (
              <option key={m} value={m}>
                {MODE_LABEL[m]}
              </option>
            ))}
          </select>
        </label>
        <button className="on" disabled={!docId || running} onClick={start}>
          Dify 로 투입
        </button>
      </div>
      {docs && !docs.some((d) => d.doc_id === LIVE_DEFAULT_DOC_ID) && (
        <p className="muted">기본 문서가 이 실행의 목록에 없다 - 문서를 직접 고른다</p>
      )}
      {error && <div className="notice error">오류 : {error}</div>}
      {record && (
        <ol className="steps">
          <Step
            state={record.workflow_run_id ? 'done' : record.status === 'failed' ? 'fail' : 'active'}
            label="① Dify 실행 시작"
            detail={record.workflow_run_id ? `workflow_run_id ${record.workflow_run_id.slice(0, 8)}` : undefined}
          />
          <Step
            state={record.job_id ? 'done' : record.status === 'failed' ? 'fail' : record.workflow_run_id ? 'active' : 'todo'}
            label="② 하니스 작업"
            detail={record.job_id ? `job_id ${record.job_id.slice(0, 8)}` : undefined}
          />
          <Step
            state={step3}
            label={record.status === 'failed' ? '③ 실패' : '③ 완료'}
            detail={
              record.status === 'running'
                ? '진행 중'
                : `${record.elapsed_seconds ?? '?'} 초${record.error ? ` · ${record.error.error_type} : ${record.error.message}` : ''}`
            }
          />
        </ol>
      )}
      {record?.status === 'completed' && job && (
        <section className="live-result">
          <h2>이번 처리의 노트</h2>
          {job.result && !('notes' in job.result) && (
            <div className="notice error">{`${job.result.error_type} : ${job.result.message}`}</div>
          )}
          {result && (
            <ul className="live-notes">
              {result.notes.map((note, index) => (
                <li key={note.note_id ?? `fail-${index}`}>
                  {note.note_id === null ? (
                    <span className="kind kind-up">{`배치 실패 : ${note.problems.join(', ')}`}</span>
                  ) : (
                    <>
                      <strong>{note.title}</strong>{' '}
                      <span className="badge" style={{ background: LAYER_COLOR[note.layer ?? ''] }}>{note.layer}</span>
                      {note.group_label ? ` ${note.group_label}` : ''}
                      <span className="muted">{` · 상향 링크 ${note.upward_links.length} · 하향 조건부 링크 ${note.downward_links.length}`}</span>
                    </>
                  )}
                </li>
              ))}
            </ul>
          )}
          {record.job_id && (
            <button className="on" onClick={() => onOverlay(record.mode, record.job_id!)}>
              이 결과를 볼트에 겹쳐 보기
            </button>
          )}
        </section>
      )}
    </div>
  )
}
