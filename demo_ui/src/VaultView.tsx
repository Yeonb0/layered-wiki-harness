// 사용자 결정 2026-10-21 · 23 : 시연 경로 전용 화면 - 보는 사람별 거르기는 서버가 하고 화면은 받은 것만 그린다
import { useCallback, useEffect, useMemo, useState } from 'react'
import { MarkerType, ReactFlow, ReactFlowProvider, useReactFlow, type Edge, type Node } from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { fetchView, type Mode, type Viewer, type ViewResponse } from './api'
import { DOWNWARD_COLOR, LAYER_COLOR, UPWARD_COLOR } from './colors'
import { buildEdges, type LinkEdge } from './edges'
import { layoutNotes, NODE_H, NODE_W } from './layout'
import { BandNode, CellNode, NoteNode, type NoteFlowNode } from './NoteNode'
import { NoteDetail } from './NoteDetail'

const NODE_TYPES = { note: NoteNode, cell: CellNode, band: BandNode }
const MODE_LABEL: Record<Mode, string> = { all_layers: '전 층 열람', split_by_layer: '층별 분리' }

export function VaultView({
  viewer,
  showNames,
  onChangeViewer,
}: {
  viewer: Viewer
  showNames: boolean
  onChangeViewer: () => void
}) {
  const [mode, setMode] = useState<Mode>('all_layers')
  const [data, setData] = useState<ViewResponse | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setData(null)
    setError(null)
    fetchView(mode, viewer.viewer_id)
      .then((response) => {
        if (!cancelled) setData(response)
      })
      .catch((e: unknown) => {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e))
      })
    return () => {
      cancelled = true
    }
  }, [mode, viewer.viewer_id])

  return (
    <div className="vault">
      <header className="bar">
        <div>
          <span className="muted">지금 보는 사람</span> <strong>{viewer.label}</strong> ( {viewer.layer} )
          {!showNames && <span className="notice warn inline">이름 · 본문이 가려짐</span>}
        </div>
        <div className="modes">
          {(Object.keys(MODE_LABEL) as Mode[]).map((m) => (
            <button key={m} className={m === mode ? 'on' : ''} onClick={() => setMode(m)}>
              {MODE_LABEL[m]}
            </button>
          ))}
        </div>
        {data && (
          <div className="counts">
            <span>열린 하향 조건부 링크 <b>{data.counts.conditional_links_opened}</b></span>
            <span>가려진 하향 조건부 링크 <b>{data.counts.conditional_links_hidden}</b></span>
            <span>가려진 상향 링크 <b>{data.counts.upward_links_hidden}</b></span>
          </div>
        )}
        <button onClick={onChangeViewer}>보는 사람 바꾸기</button>
      </header>
      {error && <div className="notice error">오류 : {error}</div>}
      {!error && !data && <div className="notice">불러오는 중</div>}
      {data && (
        <ReactFlowProvider>
          <Canvas key={`${data.mode}|${data.viewer_id}`} data={data} />
        </ReactFlowProvider>
      )}
    </div>
  )
}

function toFlowEdge(edge: LinkEdge): Edge {
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
    style: { stroke: color, strokeWidth: 2, strokeDasharray: edge.kind === 'downward' ? '8 6' : undefined },
  }
}

function Canvas({ data }: { data: ViewResponse }) {
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const { setCenter } = useReactFlow()
  const layout = useMemo(() => layoutNotes(data.notes), [data.notes])
  const edges = useMemo(() => buildEdges(data.notes).map(toFlowEdge), [data.notes])
  const titles = useMemo(() => new Map(data.notes.map((n) => [n.note_id, n.title])), [data.notes])
  const nodes = useMemo(() => {
    const out: Node[] = []
    for (const band of layout.bands) {
      out.push({
        id: `band:${band.band}`, type: 'band', position: { x: -20, y: band.y },
        data: { label: band.band, color: LAYER_COLOR[band.band] }, draggable: false, selectable: false, focusable: false,
        zIndex: -2, style: { width: Math.max(layout.width, 300) + 40, height: band.height },
      })
    }
    for (const cell of layout.cells) {
      out.push({
        id: `cell:${cell.band}:${cell.label}`, type: 'cell', position: { x: cell.x, y: cell.y },
        data: { label: cell.label, color: LAYER_COLOR[cell.band] }, draggable: false, selectable: false, focusable: false,
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
  const selected = data.notes.find((n) => n.note_id === selectedId) ?? null

  const jump = useCallback(
    (noteId: string) => {
      const target = layout.nodes.find((n) => n.note.note_id === noteId)
      if (!target) return
      setSelectedId(noteId)
      void setCenter(target.x + NODE_W / 2, target.y + NODE_H / 2, { zoom: 1, duration: 400 })
    },
    [layout, setCenter],
  )

  return (
    <div className="stage">
      <div className="canvas">
        <ReactFlow
          nodes={nodes}
          edges={edges}
          nodeTypes={NODE_TYPES}
          colorMode="dark"
          fitView
          nodesDraggable={false}
          nodesConnectable={false}
          onNodeClick={(_, node) => {
            if (node.type === 'note') setSelectedId(node.id)
          }}
          onPaneClick={() => setSelectedId(null)}
        />
        <Legend />
      </div>
      {selected && <NoteDetail note={selected} titles={titles} onJump={jump} onClose={() => setSelectedId(null)} />}
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
