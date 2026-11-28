// 사용자 결정 2026-10-23 : 왼쪽 탐색기 - 서버 응답에 있는 노트만 폴더 트리로 보이고 노트를 누르면 노트 탭으로 연다
import { useMemo, useState, type CSSProperties } from 'react'
import type { Mode, Viewer, ViewNote } from './api'
import { LAYER_COLOR } from './colors'
import type { Band } from './layout'
import { buildTree } from './tree'
import type { OpenEvent } from './tabs'

export const MODE_LABEL: Record<Mode, string> = { all_layers: '전 층 열람', split_by_layer: '층별 분리' }

// 사용자 요청 2026-11-28 : 보는 사람 · 모드 고르기는 위쪽 막대로 옮기고 탐색기는 노트 목록만 크게 보인다
export function Sidebar({
  viewer,
  mode,
  otherModeCounts,
  notes,
  activeNoteId,
  onOpenNote,
}: {
  viewer: Viewer
  mode: Mode
  // 다른 모드의 층별 노트 수 - 빈 층 안내에만 쓰고, 아직 못 불러왔으면 null
  otherModeCounts: Record<Band, number> | null
  notes: ViewNote[] | null
  activeNoteId: string | null
  onOpenNote: (noteId: string, ev?: OpenEvent) => void
}) {
  const tree = useMemo(() => (notes ? buildTree(notes) : null), [notes])
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set())
  const toggle = (key: string) =>
    setCollapsed((prev) => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  const folder = (key: string, label: string, count: number, color: string, depth: number) => (
    <button
      key={key}
      className={depth === 0 ? 'folder layer-folder' : 'folder group-folder'}
      style={{ color, '--layer': color } as CSSProperties}
      aria-expanded={!collapsed.has(key)}
      onClick={() => toggle(key)}
    >
      <span className="caret">{collapsed.has(key) ? '▸' : '▾'}</span>
      {label}
      <span className="count">{count}</span>
    </button>
  )
  const otherMode: Mode = mode === 'all_layers' ? 'split_by_layer' : 'all_layers'
  const emptyHint = (layer: Band) => {
    const other = otherModeCounts ? otherModeCounts[layer] : 0
    return other > 0
      ? `이 모드에서는 ${layer} 노트가 없습니다. ${MODE_LABEL[otherMode]}로 바꾸면 ${other}개가 보입니다.`
      : `보이는 ${layer} 노트 없음`
  }
  const noteItem = (note: ViewNote) => (
    <button
      key={note.note_id}
      className={note.note_id === activeNoteId ? 'file on' : 'file'}
      title={note.title}
      onClick={(e) => onOpenNote(note.note_id, e)}
      onAuxClick={(e) => e.button === 1 && onOpenNote(note.note_id, e)}
    >
      {note.title}
    </button>
  )
  return (
    <nav className="sidebar" aria-label="탐색기">
      <h2 className="side-head">{`${viewer.label} 에게 보이는 노트`}</h2>
      <div className="tree">
        {!tree && <p className="muted pad">불러오는 중</p>}
        {tree?.map((layer) => {
          const key = `layer:${layer.layer}`
          const color = LAYER_COLOR[layer.layer]
          return (
            <div key={key} className="tree-layer">
              {folder(key, layer.layer, layer.count, color, 0)}
              {!collapsed.has(key) && layer.count === 0 && <p className="empty">{emptyHint(layer.layer)}</p>}
              {!collapsed.has(key) && layer.count > 0 && (
                <div className="tree-children" style={{ '--layer': color } as CSSProperties}>
                  {layer.groups.map((group) => {
                    // 그룹이 없는 노트 ( 전사 ) 는 층 폴더 바로 아래에 놓는다
                    if (group.label === null) return group.notes.map((note) => noteItem(note))
                    const groupKey = `${key}:${group.label}`
                    return (
                      <div key={groupKey}>
                        {folder(groupKey, group.label, group.notes.length, 'var(--muted)', 1)}
                        {!collapsed.has(groupKey) && group.notes.map((note) => noteItem(note))}
                      </div>
                    )
                  })}
                </div>
              )}
            </div>
          )
        })}
      </div>
    </nav>
  )
}
