// 사용자 결정 2026-10-23 : 왼쪽 탐색기 - 서버 응답에 있는 노트만 폴더 트리로 보이고 노트를 누르면 노트 탭으로 연다
import { useMemo, useState } from 'react'
import type { Mode, Viewer, ViewNote } from './api'
import { LAYER_COLOR } from './colors'
import { buildTree } from './tree'

export const MODE_LABEL: Record<Mode, string> = { all_layers: '전 층 열람', split_by_layer: '층별 분리' }

export function Sidebar({
  viewer,
  mode,
  onMode,
  notes,
  activeNoteId,
  onOpenNote,
}: {
  viewer: Viewer
  mode: Mode
  onMode: (mode: Mode) => void
  notes: ViewNote[] | null
  activeNoteId: string | null
  onOpenNote: (noteId: string) => void
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
    <button key={key} className="folder" style={{ paddingLeft: 8 + depth * 14, color }} onClick={() => toggle(key)}>
      <span className="caret">{collapsed.has(key) ? '▸' : '▾'}</span>
      {label}
      <span className="count">{count}</span>
    </button>
  )
  const noteItem = (note: ViewNote, depth: number) => (
    <button
      key={note.note_id}
      className={note.note_id === activeNoteId ? 'file on' : 'file'}
      style={{ paddingLeft: 8 + depth * 14 }}
      title={note.title}
      onClick={() => onOpenNote(note.note_id)}
    >
      {note.title}
    </button>
  )
  return (
    <nav className="sidebar">
      <div className="side-top">
        <div>
          <span className="muted">지금 보는 사람</span>
          <div>
            <strong>{viewer.label}</strong> ( {viewer.layer} )
          </div>
        </div>
        <div className="modes">
          {(Object.keys(MODE_LABEL) as Mode[]).map((m) => (
            <button key={m} className={m === mode ? 'on' : ''} onClick={() => onMode(m)}>
              {MODE_LABEL[m]}
            </button>
          ))}
        </div>
      </div>
      <div className="tree">
        {!tree && <p className="muted pad">불러오는 중</p>}
        {tree?.map((layer) => {
          const key = `layer:${layer.layer}`
          return (
            <div key={key}>
              {folder(key, layer.layer, layer.count, LAYER_COLOR[layer.layer], 0)}
              {!collapsed.has(key) && layer.count === 0 && <p className="muted empty" style={{ paddingLeft: 22 }}>보이는 노트 없음</p>}
              {!collapsed.has(key) &&
                layer.groups.map((group) => {
                  // 그룹이 없는 노트 ( 전사 ) 는 층 폴더 바로 아래에 놓는다
                  if (group.label === null) return group.notes.map((note) => noteItem(note, 1))
                  const groupKey = `${key}:${group.label}`
                  return (
                    <div key={groupKey}>
                      {folder(groupKey, group.label, group.notes.length, LAYER_COLOR[layer.layer], 1)}
                      {!collapsed.has(groupKey) && group.notes.map((note) => noteItem(note, 2))}
                    </div>
                  )
                })}
            </div>
          )
        })}
      </div>
    </nav>
  )
}
