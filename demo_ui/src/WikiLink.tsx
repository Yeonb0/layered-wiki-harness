// 사용자 요청 2026-10-23 : 링크 이동을 옵시디언처럼 ( 같은 탭 이동 · Ctrl+클릭 새 탭 · 뒤로 / 앞으로 · 미리보기 ). 링크는 에이전트가 만든 것만 그린다 - 본문 글자에 링크를 새로 걸지 않는다 ( 지침 3절 20 )
// 에이전트가 만든 링크 한 개 - 지금 보기에 있으면 [[ 제목 ]] 버튼이고 없으면 눌 수 없는 회색 글자다
import { useEffect, useRef, useState } from 'react'
import type { ViewNote } from './api'
import { LinkPreview } from './LinkPreview'
import type { OpenEvent } from './tabs'

const HOVER_MS = 400

export function WikiLink({
  noteId,
  notesById,
  onOpenNote,
}: {
  noteId: string
  notesById: Map<string, ViewNote>
  onOpenNote: (noteId: string, ev?: OpenEvent) => void
}) {
  const [anchor, setAnchor] = useState<DOMRect | null>(null)
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  const note = notesById.get(noteId)
  const clear = () => {
    if (timer.current !== undefined) clearTimeout(timer.current)
    timer.current = undefined
  }
  const close = () => {
    clear()
    setAnchor(null)
  }
  useEffect(() => clear, [])
  if (!note) return <span className="wikilink missing">{`[[ ${noteId} ]]`}</span>
  return (
    <>
      <button
        className="wikilink"
        onClick={(e) => {
          close()
          onOpenNote(noteId, e)
        }}
        onAuxClick={(e) => {
          if (e.button === 1) {
            close()
            onOpenNote(noteId, e)
          }
        }}
        onMouseEnter={(e) => {
          const rect = e.currentTarget.getBoundingClientRect()
          clear()
          timer.current = setTimeout(() => setAnchor(rect), HOVER_MS)
        }}
        onMouseLeave={close}
        onFocus={(e) => {
          clear()
          setAnchor(e.currentTarget.getBoundingClientRect())
        }}
        onBlur={close}
        onKeyDown={(e) => {
          if (e.key === 'Escape') close()
        }}
      >
        {`[[ ${note.title} ]]`}
      </button>
      {anchor && <LinkPreview note={note} anchor={anchor} />}
    </>
  )
}
