// 사용자 결정 2026-10-23 : 문서 보기는 옵시디언 느낌 ( 좁은 읽기 폭, 접히는 속성 블록, [[ 내부 링크 ]] )
// 사용자 결정 2026-10-23 : 노트 탭은 읽기 화면 - 이 노트가 가리키는 링크만 칩으로 보이고 들어오는 링크는 보이지 않는다
import { useState } from 'react'
import type { ViewNote } from './api'
import { bodyLines } from './body'
import { LAYER_COLOR } from './colors'
import { classifyMarker, findMarkers, MARKER_KIND_LABEL, splitByMarkers } from './markers'
import type { OpenEvent } from './tabs'
import { WikiLink } from './WikiLink'

export function NoteReader({
  note,
  notesById,
  showNames,
  onOpenNote,
}: {
  note: ViewNote
  // 지금 보기의 노트 - 링크 이름 · 미리보기는 여기서만 찾는다
  notesById: Map<string, ViewNote>
  showNames: boolean
  onOpenNote: (noteId: string, ev?: OpenEvent) => void
}) {
  // 속성 블록은 옵시디언처럼 머리를 누르면 접히고 기본은 펼침이다
  const [propsOpen, setPropsOpen] = useState(true)
  // 본문이 가려진 실행에서는 표지를 찾지 않는다 - 가린 문구에서 표지가 나올 수 없다
  const markerHits = showNames ? findMarkers(note) : []
  const marked = (text: string) =>
    showNames
      ? splitByMarkers(text).map((piece, index) =>
          piece.marker ? (
            <mark key={index} className={`mk mk-${classifyMarker(note, piece.marker)}`} title={MARKER_KIND_LABEL[classifyMarker(note, piece.marker)]}>
              {piece.text}
            </mark>
          ) : (
            <span key={index}>{piece.text}</span>
          ),
        )
      : text
  const chips = (ids: string[]) =>
    ids.length === 0 ? (
      <span className="muted">없음</span>
    ) : (
      <span className="chips">
        {ids.map((id) => (
          <WikiLink key={id} noteId={id} notesById={notesById} onOpenNote={onOpenNote} />
        ))}
      </span>
    )
  return (
    <article className="reader">
      <h1>{note.title}</h1>
      <div className="obs-props">
        <button className="obs-props-head" aria-expanded={propsOpen} onClick={() => setPropsOpen((open) => !open)}>
          <span className="caret">{propsOpen ? '▾' : '▸'}</span>속성
        </button>
        {propsOpen && (
      <dl className="obs-dl">
        <dt>층</dt>
        <dd>
          <span className="badge" style={{ background: LAYER_COLOR[note.layer] }}>{note.layer}</span>
        </dd>
        <dt>그룹</dt>
        <dd>{note.group_label ?? '없음'}</dd>
        <dt>상향 링크</dt>
        <dd>{chips(note.upward_links)}</dd>
        <dt>열린 하향 조건부 링크</dt>
        <dd>{chips(note.opened_downward_links)}</dd>
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
        <dt>표지</dt>
        <dd>
          {!showNames && <span className="muted">판정하지 않음 ( 본문이 가려진 실행 )</span>}
          {showNames && markerHits.length === 0 && '없음'}
          {markerHits.map((hit) => (
            <div key={hit.marker.text}>
              {`${hit.marker.text} × ${hit.count} · `}
              <span className={`kind kind-${hit.kind}`}>{MARKER_KIND_LABEL[hit.kind]}</span>
            </div>
          ))}
        </dd>
      </dl>
        )}
      </div>
      <div className="body">
        {bodyLines(note.body).map((line, index) =>
          line.kind === 'heading' ? (
            <div key={index} className="sub">
              {marked(line.text)}
            </div>
          ) : (
            <div key={index} className="line">
              {line.text ? marked(line.text) : ' '}
            </div>
          ),
        )}
      </div>
    </article>
  )
}
