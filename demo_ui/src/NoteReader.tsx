// 사용자 결정 2026-10-23 : 노트 탭은 읽기 화면 - 이 노트가 가리키는 링크만 칩으로 보이고 들어오는 링크는 보이지 않는다
import type { ViewNote } from './api'
import { bodyLines } from './body'
import { LAYER_COLOR } from './colors'

export function NoteReader({
  note,
  titles,
  onOpenNote,
}: {
  note: ViewNote
  titles: Map<string, string>
  onOpenNote: (noteId: string) => void
}) {
  const chips = (ids: string[]) =>
    ids.length === 0 ? (
      <span className="muted">없음</span>
    ) : (
      <span className="chips">
        {ids.map((id) => (
          <button key={id} className="chip" onClick={() => onOpenNote(id)}>
            {`[[ ${titles.get(id) ?? id} ]]`}
          </button>
        ))}
      </span>
    )
  return (
    <article className="reader">
      <h1>{note.title}</h1>
      <dl className="props">
        <dt>층</dt>
        <dd>
          <span className="badge" style={{ background: LAYER_COLOR[note.layer] }}>{note.layer}</span>
        </dd>
        <dt>그룹</dt>
        <dd>{note.group_label ?? '없음'}</dd>
        <dt>출처 문서</dt>
        <dd className="mono">{note.source_doc_id}</dd>
        <dt>출처 세그먼트 ( {note.source_segment_ids.length} )</dt>
        <dd className="mono">
          {note.source_segment_ids.map((id) => (
            <div key={id}>{id}</div>
          ))}
        </dd>
        <dt>inserted_at_vault_size</dt>
        <dd>{note.inserted_at_vault_size}</dd>
      </dl>
      <div className="body">
        {bodyLines(note.body).map((line, index) =>
          line.kind === 'heading' ? (
            <div key={index} className="sub">
              {line.text}
            </div>
          ) : (
            <div key={index} className="line">
              {line.text || ' '}
            </div>
          ),
        )}
      </div>
      <h3>상향 링크</h3>
      {chips(note.upward_links)}
      <h3>열린 하향 조건부 링크</h3>
      {chips(note.opened_downward_links)}
    </article>
  )
}
