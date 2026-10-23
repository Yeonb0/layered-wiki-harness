// 사용자 결정 2026-10-23 : 보는 사람 비교 - 서버가 거른 두 보기를 note_id 로 나누기만 하고 화면이 노트를 거르지 않는다
import { useState } from 'react'
import type { Viewer, ViewNote, ViewResponse } from './api'
import { LAYER_COLOR } from './colors'
import { compareViews } from './compare'
import { BANDS } from './layout'
import { MODE_LABEL } from './Sidebar'
import { useView } from './useView'

function Column({
  title,
  notes,
  onOpen,
}: {
  title: string
  notes: ViewNote[]
  onOpen: ((noteId: string) => void) | null
}) {
  return (
    <section className="cmp-col">
      <h3>
        {title} <span className="count">{notes.length}</span>
      </h3>
      {notes.length === 0 && <p className="muted">없음</p>}
      {BANDS.map((layer) => {
        const inLayer = notes.filter((note) => note.layer === layer)
        if (inLayer.length === 0) return null
        return (
          <div key={layer} className="cmp-layer">
            <div>
              <span className="badge" style={{ background: LAYER_COLOR[layer] }}>{layer}</span>{' '}
              <span className="muted">{inLayer.length}</span>
            </div>
            <ul>
              {inLayer.map((note) => (
                <li key={note.note_id}>
                  {onOpen ? (
                    <button className="link" onClick={() => onOpen(note.note_id)}>
                      {note.title}
                      {note.group_label ? ` ( ${note.group_label} )` : ''}
                    </button>
                  ) : (
                    // A 의 보기에 없는 노트라 열 수 없다 - 회색으로만 보인다
                    <span className="gray">
                      {note.title}
                      {note.group_label ? ` ( ${note.group_label} )` : ''}
                    </span>
                  )}
                </li>
              ))}
            </ul>
          </div>
        )
      })}
    </section>
  )
}

export function CompareViewer({
  viewer,
  viewers,
  mode,
  viewA,
  jobId,
  onOpenNote,
}: {
  viewer: Viewer
  viewers: Viewer[]
  mode: keyof typeof MODE_LABEL
  viewA: ViewResponse | null
  // 라이브 겹침이 이 모드에 걸려 있으면 B 의 보기에도 같은 작업을 겹친다
  jobId: string | null
  onOpenNote: (noteId: string) => void
}) {
  const [bId, setBId] = useState<string | null>(null)
  const b = useView(mode, bId, jobId)
  // 목록은 App 이 받은 보는 사람에서 A ( 지금 보는 사람 ) 를 뺀 것이다
  const candidates = viewers.filter((v) => v.viewer_id !== viewer.viewer_id)
  // 모드를 바꾼 직후에는 B 의 이전 모드 응답이 잠깐 남을 수 있어 같은 모드일 때만 나눈다
  const ready = viewA !== null && b.data !== null && viewA.mode === b.data.mode
  const result = ready ? compareViews(viewA, b.data!) : null
  return (
    <div className="cmp">
      <h1>보는 사람 비교</h1>
      <p className="muted">
        A : <strong>{viewer.label}</strong> ( {viewer.layer} ) · 모드 : {MODE_LABEL[mode]} · 서버가 거른 두 보기를 나눠 보여 줄 뿐이다
      </p>
      <label>
        B ( 비교할 보는 사람 ){' '}
        <select value={bId ?? ''} onChange={(e) => setBId(e.target.value === '' ? null : e.target.value)}>
          <option value="">선택 안 함</option>
          {candidates.map((v) => (
            <option key={v.viewer_id} value={v.viewer_id}>
              {v.label} ( {v.layer} )
            </option>
          ))}
        </select>
      </label>
      {bId === null && <p className="notice">비교할 보는 사람을 고른다</p>}
      {bId !== null && b.error && <div className="notice error">오류 : {b.error}</div>}
      {bId !== null && !b.error && !result && <div className="notice">불러오는 중</div>}
      {result && (
        <div className="cmp-cols">
          <Column title="둘 다 보임" notes={result.both} onOpen={onOpenNote} />
          <Column title="A 에게만" notes={result.onlyA} onOpen={onOpenNote} />
          <Column title="B 에게만" notes={result.onlyB} onOpen={null} />
        </div>
      )}
    </div>
  )
}
