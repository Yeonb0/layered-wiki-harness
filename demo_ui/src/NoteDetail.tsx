// 사용자 결정 2026-10-21 · 23 : 시연 경로 전용 화면 - 오른쪽 패널은 응답에 있는 필드만 보인다
import type { ViewNote } from './api'
import { bodyLines } from './body'
import { LAYER_COLOR } from './colors'

export function NoteDetail({
  note,
  titles,
  onJump,
  onClose,
}: {
  note: ViewNote
  titles: Map<string, string>
  onJump: (noteId: string) => void
  onClose: () => void
}) {
  const links = (ids: string[]) =>
    ids.length === 0 ? (
      <p className="muted">없음</p>
    ) : (
      <ul>
        {ids.map((id) => (
          <li key={id}>
            <button className="link" onClick={() => onJump(id)}>
              {titles.get(id) ?? id}
            </button>
          </li>
        ))}
      </ul>
    )
  return (
    <aside className="detail">
      <button className="close" onClick={onClose}>
        닫기
      </button>
      <h2>{note.title}</h2>
      <p>
        <span className="badge" style={{ background: LAYER_COLOR[note.layer] }}>
          {note.layer}
          {note.group_label ? ` · ${note.group_label}` : ''}
        </span>
      </p>
      <h3>출처 문서</h3>
      <p className="mono">{note.source_doc_id}</p>
      <h3>출처 세그먼트 ( {note.source_segment_ids.length} )</h3>
      <ul className="mono">
        {note.source_segment_ids.map((id) => (
          <li key={id}>{id}</li>
        ))}
      </ul>
      <h3>본문</h3>
      <div className="body">
        {bodyLines(note.body).map((line, index) =>
          line.kind === 'heading' ? (
            <div key={index} className="sub">
              {line.text}
            </div>
          ) : (
            <div key={index} className="line">
              {line.text || '\u00a0'}
            </div>
          ),
        )}
      </div>
      <h3>상향 링크</h3>
      {links(note.upward_links)}
      <h3>열린 하향 조건부 링크</h3>
      {links(note.opened_downward_links)}
    </aside>
  )
}
