// 사용자 결정 2026-10-21 · 23 : 시연 경로 전용 화면 - 그래프 탭은 서버가 거른 노트만 그리고, 노드를 누르면 그 노트 탭을 연다
import { useMemo } from 'react'
import { MarkerType, ReactFlow, ReactFlowProvider, type Edge, type Node } from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import type { ViewResponse } from './api'
import { DOWNWARD_COLOR, LAYER_COLOR, UPWARD_COLOR } from './colors'
import { buildEdges, edgeStyle, filterEdges, type LinkEdge } from './edges'
import { layoutNotes } from './layout'
import { BandNode, CellNode, NoteNode, type NoteFlowNode } from './NoteNode'

const NODE_TYPES = { note: NoteNode, cell: CellNode, band: BandNode }

function toFlowEdge(edge: LinkEdge, selectedId: string | null): Edge {
  const look = edgeStyle(edge, selectedId)
  const color = edge.kind === 'upward' ? UPWARD_COLOR : DOWNWARD_COLOR
  // 같은 층 링크는 위쪽 핸들끼리 ( 상향 ) 또는 아래쪽 핸들끼리 ( 하향 ) 이어 옆 노드로 돌아가지 않게 한다
  const handles =
    edge.kind === 'upward'
      ? { sourceHandle: 'top-s', targetHandle: edge.sameLayer ? 'top-t' : 'bottom-t' }
      : { sourceHandle: 'bottom-s', targetHandle: edge.sameLayer ? 'bottom-t' : 'top-t' }
  return {
    id: edge.id,
    source: edge.source,
    target: edge.target,
    ...handles,
    markerEnd: { type: MarkerType.ArrowClosed, color },
    zIndex: look.zIndex,
    style: {
      stroke: color,
      strokeWidth: look.strokeWidth,
      opacity: look.opacity,
      strokeDasharray: edge.kind === 'downward' ? '8 6' : undefined,
    },
  }
}

export function GraphTab({
  data,
  showSameLayer,
  onToggleSameLayer,
  selectedId,
  onOpenNote,
}: {
  data: ViewResponse
  showSameLayer: boolean
  onToggleSameLayer: (value: boolean) => void
  selectedId: string | null
  onOpenNote: (noteId: string) => void
}) {
  const layout = useMemo(() => layoutNotes(data.notes), [data.notes])
  const allEdges = useMemo(() => buildEdges(data.notes), [data.notes])
  const edges = useMemo(
    () => filterEdges(allEdges, showSameLayer).map((edge) => toFlowEdge(edge, selectedId)),
    [allEdges, showSameLayer, selectedId],
  )
  const nodes = useMemo(() => {
    const out: Node[] = []
    for (const band of layout.bands) {
      out.push({
        id: `band:${band.band}`, type: 'band', position: { x: -20, y: band.y },
        data: {
          label: band.band,
          color: LAYER_COLOR[band.band],
          emptyText: band.empty ? `이 보기에서 보이는 ${band.band} 노트 없음` : null,
        },
        draggable: false, selectable: false, focusable: false,
        zIndex: -2, style: { width: Math.max(layout.width, 300) + 40, height: band.height },
      })
    }
    for (const cell of layout.cells) {
      out.push({
        id: `cell:${cell.band}:${cell.label}`, type: 'cell', position: { x: cell.x, y: cell.y },
        // 칸 이름이 띠 이름과 같으면 ( 전사 ) 칸 이름을 쓰지 않는다
        data: { label: cell.label === cell.band ? '' : cell.label, color: LAYER_COLOR[cell.band] },
        draggable: false, selectable: false, focusable: false,
        zIndex: -1, style: { width: cell.width, height: cell.height },
      })
    }
    for (const item of layout.nodes) {
      const node: NoteFlowNode = {
        id: item.note.note_id, type: 'note', position: { x: item.x, y: item.y },
        data: { note: item.note, selected: item.note.note_id === selectedId }, draggable: false,
      }
      out.push(node)
    }
    return out
  }, [layout, selectedId])

  return (
    <div className="graph-tab">
      <div className="graph-bar">
        {/* 화면 표시 선택일 뿐 데이터는 그대로다 */}
        <label className="toggle">
          <input type="checkbox" checked={showSameLayer} onChange={(e) => onToggleSameLayer(e.target.checked)} />
          같은 층 링크 보기
        </label>
      </div>
      <div className="canvas">
        <ReactFlowProvider>
          <ReactFlow
            nodes={nodes}
            edges={edges}
            nodeTypes={NODE_TYPES}
            colorMode="dark"
            fitView
            nodesDraggable={false}
            nodesConnectable={false}
            onNodeClick={(_, node) => {
              if (node.type === 'note') onOpenNote(node.id)
            }}
          />
        </ReactFlowProvider>
        <Legend />
      </div>
    </div>
  )
}

function Legend() {
  return (
    <div className="legend">
      <div>
        <svg width="40" height="10"><line x1="0" y1="5" x2="40" y2="5" stroke={UPWARD_COLOR} strokeWidth="2" /></svg>
        상향 링크 ( 아래 → 위, 같은 층 포함 )
      </div>
      <div>
        <svg width="40" height="10">
          <line x1="0" y1="5" x2="40" y2="5" stroke={DOWNWARD_COLOR} strokeWidth="2" strokeDasharray="8 6" />
        </svg>
        열린 하향 조건부 링크 ( 위 → 아래 )
      </div>
    </div>
  )
}
