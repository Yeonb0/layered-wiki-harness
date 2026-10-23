// 사용자 결정 2026-10-23 ( 지침 v3.1 ) : 회의록 투입 ( 차수 901 ) → 에이전트 분해 · 배치 → 참석자가 노트별 승인 / 반려 → 승인된 노트만 볼트에 겹친다. 승인 게이트는 승격이 아니다
// 판정 기록 보기 ( 12주 감사로그 ) - 보는 사람이 볼 수 있는 후보만, 가려진 후보는 개수만, 근거는 서버가 가린 그대로
import { useEffect, useState } from 'react'
import { fetchTrace, type Trace, type Viewer } from './api'
import { LAYER_COLOR } from './colors'
import { Toggle } from './Toggle'

const tail = (id: string) => id.slice(-8)

function TraceBody({ viewer, docId }: { viewer: Viewer; docId: string }) {
  const [trace, setTrace] = useState<Trace | null>(null)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    let alive = true
    fetchTrace(viewer.viewer_id, docId)
      .then((t) => alive && setTrace(t))
      .catch((e: unknown) => alive && setError((e as Error).message))
    return () => {
      alive = false
    }
  }, [viewer.viewer_id, docId])
  if (error) return <div className="notice error">{error}</div>
  if (!trace) return <div className="notice">불러오는 중</div>
  const titleOf = new Map(trace.decompose.notes.map((n) => [n.note_index, n.title]))
  return (
    <div className="trace">
      <h4>분해 : 세그먼트 → 노트</h4>
      {!trace.decompose.ok && <div className="notice error">분해 실패 : {trace.decompose.error}</div>}
      <table className="db-table trace-table">
        <thead>
          <tr>
            <th>노트</th>
            <th>세그먼트</th>
          </tr>
        </thead>
        <tbody>
          {trace.decompose.notes.map((n) => (
            <tr key={n.note_index}>
              <td>{n.title}</td>
              <td className="mono">{n.segment_ids.map(tail).join(', ')}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {trace.places.map((place) => (
        <div key={place.note_index} className="trace-place">
          <h4>
            {titleOf.get(place.note_index) ?? `노트 ${place.note_index}`}{' '}
            {place.layer !== null ? (
              <span className="badge" style={{ background: LAYER_COLOR[place.layer] }}>
                {place.layer}
              </span>
            ) : (
              <span className="badge failed">배치 실패</span>
            )}
          </h4>
          <p className="muted">
            상향 링크 {place.upward_links.length > 0 ? place.upward_links.map(tail).join(', ') : '없음'} · 하향 링크{' '}
            {place.downward_links.length > 0 ? place.downward_links.map(tail).join(', ') : '없음'}
            {place.hidden_links > 0 && ` · 보이지 않는 링크 ${place.hidden_links}`}
          </p>
          <table className="db-table trace-table">
            <thead>
              <tr>
                <th>후보</th>
                <th>층</th>
                <th>그룹</th>
                <th>제목</th>
              </tr>
            </thead>
            <tbody>
              {place.candidates.map((c) => (
                <tr key={c.id}>
                  <td className="mono">{tail(c.id)}</td>
                  <td>{c.layer}</td>
                  <td>{c.group_label ?? <span className="muted">없음</span>}</td>
                  <td>{c.title}</td>
                </tr>
              ))}
              {place.candidates.length === 0 && (
                <tr>
                  <td colSpan={4} className="muted">
                    보이는 후보 없음
                  </td>
                </tr>
              )}
            </tbody>
          </table>
          <p className="muted">가려진 후보 {place.hidden_candidates}개</p>
          {place.rationale !== null ? (
            <p>{place.rationale}</p>
          ) : (
            place.rationale_hidden && <p className="muted">근거 가림 ( 보이지 않는 후보 포함 )</p>
          )}
          {place.problems.length > 0 && <p className="notice warn">{place.problems.join(' / ')}</p>}
        </div>
      ))}
    </div>
  )
}

export function TracePanel({ viewer, docId }: { viewer: Viewer; docId: string }) {
  return (
    <Toggle title="판정 기록" defaultOpen={false}>
      <TraceBody viewer={viewer} docId={docId} />
    </Toggle>
  )
}
