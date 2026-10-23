// 사용자 요청 2026-10-23 : 링크 이동을 옵시디언처럼 ( 같은 탭 이동 · Ctrl+클릭 새 탭 · 뒤로 / 앞으로 · 미리보기 ). 링크는 에이전트가 만든 것만 그린다 - 본문 글자에 링크를 새로 걸지 않는다 ( 지침 3절 20 )
// 링크 미리보기 창 - 지금 보기에 있는 노트의 내용을 그대로 보인다 ( 본문이 가려진 실행이면 가린 문구 그대로 )
import { useLayoutEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import type { ViewNote } from './api'
import { LAYER_COLOR } from './colors'

const WIDTH = 360
const MARGIN = 8
const BODY_CHARS = 200

export function LinkPreview({ note, anchor }: { note: ViewNote; anchor: DOMRect }) {
  const ref = useRef<HTMLDivElement>(null)
  const [pos, setPos] = useState<{ left: number; top: number }>({ left: anchor.left, top: anchor.bottom + 6 })
  // 그려진 크기를 재서 화면 밖으로 나가지 않게 옮긴다 - 아래가 모자라면 링크 위에 둔다
  useLayoutEffect(() => {
    const box = ref.current?.getBoundingClientRect()
    const height = box?.height ?? 0
    const width = Math.min(WIDTH, window.innerWidth - MARGIN * 2)
    const left = Math.max(MARGIN, Math.min(anchor.left, window.innerWidth - width - MARGIN))
    let top = anchor.bottom + 6
    if (top + height > window.innerHeight - MARGIN) top = Math.max(MARGIN, anchor.top - 6 - height)
    setPos({ left, top })
  }, [anchor, note])
  const body = note.body.length > BODY_CHARS ? `${note.body.slice(0, BODY_CHARS)}…` : note.body
  return createPortal(
    <div
      ref={ref}
      role="tooltip"
      className="link-preview"
      style={{ left: pos.left, top: pos.top, borderLeftColor: LAYER_COLOR[note.layer] }}
    >
      <div className="link-preview-head">
        <span className="badge" style={{ background: LAYER_COLOR[note.layer] }}>
          {note.layer}
        </span>
        {note.group_label && <span className="muted">{note.group_label}</span>}
      </div>
      <strong>{note.title}</strong>
      <p className="link-preview-body">{body}</p>
      <span className="muted">출처 세그먼트 {note.source_segment_ids.length}</span>
    </div>,
    document.body,
  )
}
