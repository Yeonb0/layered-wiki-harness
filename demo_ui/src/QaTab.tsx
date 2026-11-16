// 사용자 결정 2026-11-16 : Q&A 탭 - 화면 → 시연 API /ask → Dify 챗플로우. 지금 고른 보는 사람 · 모드를 그대로 쓴다
// 질문 · 답 기록은 이 탭 안 메모리에만 둔다 ( localStorage 에 쓰지 않는다 )
import { useEffect, useRef, useState } from 'react'
import { ApiError, postAsk, type Mode, type Viewer } from './api'
import { LAYER_COLOR } from './colors'
import { askErrorText, toQaView, type QaView } from './qaView'
import { MODE_LABEL } from './Sidebar'
import type { OpenEvent } from './tabs'

const MAX_QUERY_CHARS = 500

type Entry = { id: number; query: string; mode: Mode; viewerLabel: string; view: QaView }

export function QaTab({
  viewer,
  mode,
  onOpenNote,
}: {
  viewer: Viewer
  mode: Mode
  onOpenNote: (noteId: string, ev?: OpenEvent) => void
}) {
  const [query, setQuery] = useState('')
  const [entries, setEntries] = useState<Entry[]>([])
  const [error, setError] = useState<string | null>(null)
  const [waiting, setWaiting] = useState(false)
  const [elapsed, setElapsed] = useState(0)
  const alive = useRef(true)
  const nextId = useRef(1)
  useEffect(() => {
    alive.current = true
    return () => {
      alive.current = false
    }
  }, [])

  useEffect(() => {
    if (!waiting) return
    const started = Date.now()
    setElapsed(0)
    const timer = setInterval(() => setElapsed(Math.floor((Date.now() - started) / 1000)), 1000)
    return () => clearInterval(timer)
  }, [waiting])

  const send = async () => {
    const text = query.trim()
    if (!text || waiting) return
    setError(null)
    setWaiting(true)
    try {
      const response = await postAsk(mode, viewer.viewer_id, text)
      if (!alive.current) return
      setEntries((list) => [
        { id: nextId.current++, query: text, mode, viewerLabel: viewer.label, view: toQaView(response) },
        ...list,
      ])
      setQuery('')
    } catch (e) {
      if (!alive.current) return
      setError(e instanceof ApiError ? askErrorText(e.status, e.message) : askErrorText(null, e instanceof Error ? e.message : String(e)))
    } finally {
      if (alive.current) setWaiting(false)
    }
  }

  return (
    <div className="qa">
      <h1>Q&amp;A</h1>
      <p className="muted">
        보는 사람 : {viewer.label} · 모드 : {MODE_LABEL[mode]} ( 위에서 고른 값을 그대로 쓴다 )
      </p>
      <div className="qa-form">
        <textarea
          value={query}
          maxLength={MAX_QUERY_CHARS}
          rows={3}
          placeholder="질문을 입력한다"
          disabled={waiting}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) void send()
          }}
        />
        <button onClick={() => void send()} disabled={waiting || !query.trim()}>
          보내기
        </button>
      </div>
      {waiting && <p className="notice">{`생성 중 (보통 30초 안팎) · ${elapsed}초`}</p>}
      {error && <p className="notice error">{error}</p>}
      {entries.map((entry) => (
        <section key={entry.id} className="qa-entry">
          <p className="qa-query">
            <strong>질문</strong> {entry.query}
          </p>
          <p className="muted">
            {entry.viewerLabel} · {MODE_LABEL[entry.mode]} · {entry.view.elapsedSeconds}초
          </p>
          <pre className="qa-answer">{entry.view.answer}</pre>
          {entry.view.outOfView.length > 0 && (
            <p className="notice warn">
              보기 밖 인용 {entry.view.outOfView.length}건 ( 이 보는 사람에게는 보이지 않는다 ) : {entry.view.outOfView.join(', ')}
            </p>
          )}
          <h4>근거 노트</h4>
          {entry.view.sources.length === 0 ? (
            <p className="muted">보기 안에서 인용된 노트가 없다</p>
          ) : (
            <ul className="qa-sources">
              {entry.view.sources.map((source) => (
                <li key={source.note_id}>
                  <span className="badge" style={{ background: LAYER_COLOR[source.layer] }}>
                    {source.layer}
                  </span>
                  {source.group_label && <span className="muted"> {source.group_label}</span>}{' '}
                  <button
                    className="wikilink"
                    onClick={(e) => onOpenNote(source.note_id, e)}
                    onAuxClick={(e) => e.button === 1 && onOpenNote(source.note_id, e)}
                  >
                    {`[[ ${source.title} ]]`}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </section>
      ))}
      <p className="qa-footer muted">합성 시연 코퍼스 · 메커니즘 시연이며 측정 결과가 아니다</p>
    </div>
  )
}
