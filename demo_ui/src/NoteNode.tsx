// 사용자 결정 2026-10-21 · 23 : 시연 경로 전용 화면 - 노드는 제목, 층 · 그룹 배지, 출처 세그먼트 수만 보인다
import { Handle, Position, type Node, type NodeProps } from '@xyflow/react'
import type { ViewNote } from './api'
import { LAYER_COLOR } from './colors'
import { NODE_H, NODE_W } from './layout'

export type NoteFlowNode = Node<{ note: ViewNote; selected: boolean }, 'note'>
export type CellFlowNode = Node<{ label: string; color: string }, 'cell'>
export type BandFlowNode = Node<{ label: string; color: string }, 'band'>

// 같은 위치에 겹친 핸들은 가로 위치를 달리해 상향 / 하향 엣지가 서로 다른 점에서 출발한다
const POSITION_S = { left: '35%' }
const POSITION_T = { left: '65%' }

export function NoteNode({ data }: NodeProps<NoteFlowNode>) {
  const { note, selected } = data
  const color = LAYER_COLOR[note.layer]
  return (
    <div
      className={selected ? 'note-node selected' : 'note-node'}
      style={{ width: NODE_W, height: NODE_H, borderColor: color }}
    >
      <Handle id="top-s" type="source" position={Position.Top} style={POSITION_S} />
      <Handle id="top-t" type="target" position={Position.Top} style={POSITION_T} />
      <div className="note-title" title={note.title}>
        {note.title}
      </div>
      <div className="note-meta">
        <span className="badge" style={{ background: color }}>
          {note.layer}
          {note.group_label ? ` · ${note.group_label}` : ''}
        </span>
        <span className="segs">세그먼트 {note.source_segment_ids.length}</span>
      </div>
      <Handle id="bottom-s" type="source" position={Position.Bottom} style={POSITION_S} />
      <Handle id="bottom-t" type="target" position={Position.Bottom} style={POSITION_T} />
    </div>
  )
}

export function CellNode({ data }: NodeProps<CellFlowNode>) {
  return (
    <div className="cell-box" style={{ borderColor: data.color }}>
      <span style={{ color: data.color }}>{data.label}</span>
    </div>
  )
}

export function BandNode({ data }: NodeProps<BandFlowNode>) {
  return (
    <div className="band-box" style={{ borderColor: data.color }}>
      <span style={{ color: data.color }}>{data.label}</span>
    </div>
  )
}
