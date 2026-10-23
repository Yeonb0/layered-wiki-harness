// 사용자 요청 2026-10-23 : 그래프는 옵시디언 그래프 뷰처럼 움직이고 연결이 강조되게. 지침 7절 : 층 · 링크 방향은 계속 드러낸다
// 화면은 링크를 새로 만들거나 없애지 않는다 - 서버가 거른 노트와 buildEdges · filterEdges 결과만 그린다
// 렌더는 React 가 아니라 tick 마다 d3 selection 으로 속성만 갱신한다 ( React 재렌더를 일으키지 않는다 )
import { useEffect, useMemo, useRef, useState } from 'react'
import { drag, type D3DragEvent } from 'd3-drag'
import {
  forceCollide, forceLink, forceManyBody, forceSimulation, forceX, forceY, type ForceLink, type Simulation,
  type SimulationLinkDatum, type SimulationNodeDatum,
} from 'd3-force'
import { select, type Selection } from 'd3-selection'
import { zoom, zoomIdentity, type ZoomBehavior } from 'd3-zoom'
import type { ViewResponse } from './api'
import { DOWNWARD_COLOR, LAYER_COLOR, UPWARD_COLOR } from './colors'
import { buildEdges, filterEdges, type LinkEdge } from './edges'
import { graphNodes, keepPositions, layerY, neighbors, type GNode } from './forceGraph'
import { BANDS } from './layout'
import type { OpenEvent } from './tabs'

type SimNode = GNode & SimulationNodeDatum
type SimLink = SimulationLinkDatum<SimNode> & { edge: LinkEdge }

// 움직임이 이 픽셀 미만이면 끌기가 아니라 클릭으로 본다
const CLICK_PX = 4
const LABEL_MIN_ZOOM = 0.6
const DIM_NODE = 0.15
const DIM_EDGE = 0.06

function clientPoint(event: MouseEvent | TouchEvent): { x: number; y: number } {
  if ('changedTouches' in event && event.changedTouches.length > 0) {
    return { x: event.changedTouches[0].clientX, y: event.changedTouches[0].clientY }
  }
  const mouse = event as MouseEvent
  return { x: mouse.clientX, y: mouse.clientY }
}

export function ForceGraph({
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
  onOpenNote: (noteId: string, ev?: OpenEvent) => void
}) {
  const [layerPull, setLayerPull] = useState(true)
  const [distance, setDistance] = useState(90)
  const [charge, setCharge] = useState(220)
  const [settingsOpen, setSettingsOpen] = useState(true)

  const containerRef = useRef<HTMLDivElement>(null)
  const svgRef = useRef<SVGSVGElement>(null)
  const simRef = useRef<Simulation<SimNode, SimLink> | null>(null)
  const zoomRef = useRef<ZoomBehavior<SVGSVGElement, unknown> | null>(null)
  const sizeRef = useRef({ width: 800, height: 600 })
  const positionsRef = useRef(new Map<string, { x: number; y: number }>())
  const zoomKRef = useRef(1)
  const hoverRef = useRef<string | null>(null)
  // 끌기를 시작한 화면 좌표 - 놓을 때 움직임이 CLICK_PX 미만이면 클릭으로 본다
  const dragOrigin = useRef<{ x: number; y: number } | null>(null)
  const highlightRef = useRef<(() => void) | null>(null)
  const forcesRef = useRef<(() => void) | null>(null)
  const onOpenRef = useRef(onOpenNote)
  onOpenRef.current = onOpenNote
  const selectedRef = useRef(selectedId)
  selectedRef.current = selectedId
  // 슬라이더 값은 시뮬레이션 안에서 오래된 값을 읽지 않도록 매 렌더 ref 에 둔다
  const settingsRef = useRef({ layerPull, distance, charge })
  settingsRef.current = { layerPull, distance, charge }

  const edges = useMemo(() => filterEdges(buildEdges(data.notes), showSameLayer), [data.notes, showSameLayer])
  const nodes = useMemo(() => graphNodes(data, edges), [data, edges])

  // 시뮬레이션 · 확대 이동 · 크기 관찰은 한 번만 만든다
  useEffect(() => {
    const svgElement = svgRef.current!
    const container = containerRef.current!
    const sim = forceSimulation<SimNode>()
      .force('link', forceLink<SimNode, SimLink>().id((d) => d.id))
      .force('charge', forceManyBody<SimNode>())
      .force('collide', forceCollide<SimNode>())
      .force('x', forceX<SimNode>())
      .force('y', forceY<SimNode>())
    simRef.current = sim
    const root = select(svgElement).select<SVGGElement>('g.fg-root')
    const behavior = zoom<SVGSVGElement, unknown>()
      .scaleExtent([0.3, 3])
      .on('zoom', (event) => {
        root.attr('transform', event.transform.toString())
        zoomKRef.current = event.transform.k
        highlightRef.current?.()
      })
    zoomRef.current = behavior
    // 더블클릭은 확대가 아니라 아무 일도 하지 않게 둔다 - 노드 클릭과 헷갈리지 않게
    select(svgElement).call(behavior).on('dblclick.zoom', null)
    const observer = new ResizeObserver((entries) => {
      const box = entries[0].contentRect
      sizeRef.current = { width: Math.max(box.width, 100), height: Math.max(box.height, 100) }
      forcesRef.current?.()
      sim.alpha(0.3).restart()
    })
    observer.observe(container)
    return () => {
      observer.disconnect()
      select(svgElement).on('.zoom', null)
      sim.on('tick', null)
      sim.stop()
      simRef.current = null
    }
  }, [])

  // 보기 ( 노드 · 엣지 ) 가 바뀔 때마다 요소를 다시 만들고, 같은 id 노드는 이전 좌표를 이어 받는다
  useEffect(() => {
    const sim = simRef.current!
    const root = select(svgRef.current!).select<SVGGElement>('g.fg-root')
    const edgeLayer = root.select<SVGGElement>('g.fg-edges')
    const flowLayer = root.select<SVGGElement>('g.fg-flows')
    const nodeLayer = root.select<SVGGElement>('g.fg-nodes')
    edgeLayer.selectAll('*').remove()
    flowLayer.selectAll('*').remove()
    nodeLayer.selectAll('*').remove()

    const simNodes: SimNode[] = keepPositions(positionsRef.current, nodes).map((node) => ({ ...node }))
    const simLinks: SimLink[] = edges.map((edge) => ({ source: edge.source, target: edge.target, edge }))
    const colorOf = (edge: LinkEdge) => (edge.kind === 'upward' ? UPWARD_COLOR : DOWNWARD_COLOR)

    const edgeSel = edgeLayer
      .selectAll<SVGLineElement, SimLink>('line')
      .data(simLinks)
      .join('line')
      .attr('class', (d) => `fg-edge ${d.edge.kind}`)
      .attr('stroke', (d) => colorOf(d.edge))
      .attr('stroke-dasharray', (d) => (d.edge.kind === 'downward' ? '6 4' : null))
      .attr('marker-end', (d) => `url(#fg-arrow-${d.edge.kind})`)
    // 강조된 상향 링크 위에 겹쳐 흐르는 점선 - 실선만으로는 방향이 안 보여서 흐름으로 보인다
    const flowSel = flowLayer
      .selectAll<SVGLineElement, SimLink>('line')
      .data(simLinks.filter((d) => d.edge.kind === 'upward'))
      .join('line')
      .attr('class', 'fg-flow')
      .attr('stroke', '#e8e8f0')
      .attr('stroke-dasharray', '4 6')
    const nodeSel = nodeLayer
      .selectAll<SVGGElement, SimNode>('g')
      .data(simNodes, (d) => d.id)
      .join((enter) => {
        const group = enter.append('g').attr('class', 'fg-node')
        group.append('circle')
        group.append('text')
        group.append('title')
        return group
      })
    nodeSel
      .select('circle')
      .attr('r', (d) => (d as SimNode).radius)
      .attr('fill', (d) => LAYER_COLOR[(d as SimNode).layer])
      .attr('stroke', '#1a1a1a')
      .attr('stroke-width', 1.5)
    nodeSel
      .select('text')
      .text((d) => (d as SimNode).title)
      .attr('text-anchor', 'middle')
      .attr('dy', (d) => (d as SimNode).radius + 12)
      .attr('font-size', 11)
      .attr('fill', '#e0e0e0')
    nodeSel.select('title').text((d) => `${(d as SimNode).title}${(d as SimNode).group ? ` · ${(d as SimNode).group}` : ''}`)

    const highlight = () => {
      const focus = hoverRef.current ?? selectedRef.current
      const near = focus ? neighbors(edges, focus) : null
      nodeSel.select('circle').attr('opacity', (d) => (!near || near.has((d as SimNode).id) ? 1 : DIM_NODE))
      nodeSel
        .select('text')
        .attr('opacity', (d) => {
          const on = near ? near.has((d as SimNode).id) : false
          // 확대가 작으면 강조된 노드의 이름표만 보인다
          if (zoomKRef.current < LABEL_MIN_ZOOM && !on) return 0
          return !near ? 0.75 : on ? 1 : DIM_NODE
        })
        .attr('font-weight', (d) => (near && near.has((d as SimNode).id) ? 700 : 400))
      const touches = (d: SimLink) => focus !== null && (d.edge.source === focus || d.edge.target === focus)
      edgeSel
        .classed('hl', touches)
        .attr('stroke-opacity', (d) => (focus === null ? (d.edge.sameLayer ? 0.35 : 0.8) : touches(d) ? 1 : DIM_EDGE))
        .attr('stroke-width', (d) => (touches(d) ? 2.5 : 1.5))
      flowSel.attr('opacity', (d) => (touches(d) ? 0.9 : 0)).attr('stroke-width', 2)
    }
    highlightRef.current = highlight

    const paint = () => {
      const place = (selection: Selection<SVGLineElement, SimLink, SVGGElement, unknown>) =>
        selection.each(function (d) {
          const s = d.source as SimNode
          const t = d.target as SimNode
          const dx = (t.x ?? 0) - (s.x ?? 0)
          const dy = (t.y ?? 0) - (s.y ?? 0)
          const length = Math.hypot(dx, dy) || 1
          // 화살표가 대상 원 테두리에서 멈추게 대상 반지름만큼 줄여 그린다
          const stop = t.radius + 1.5
          select(this)
            .attr('x1', s.x ?? 0)
            .attr('y1', s.y ?? 0)
            .attr('x2', (t.x ?? 0) - (dx / length) * stop)
            .attr('y2', (t.y ?? 0) - (dy / length) * stop)
        })
      place(edgeSel)
      place(flowSel)
      nodeSel.attr('transform', (d) => `translate(${d.x ?? 0},${d.y ?? 0})`)
      for (const node of simNodes) positionsRef.current.set(node.id, { x: node.x ?? 0, y: node.y ?? 0 })
    }
    sim.on('tick', paint)

    const dragBehavior = drag<SVGGElement, SimNode>()
      .on('start', (event: D3DragEvent<SVGGElement, SimNode, SimNode>, d) => {
        const origin = clientPoint(event.sourceEvent as MouseEvent | TouchEvent)
        dragOrigin.current = origin
        // 끄는 동안 위치를 고정하고 시뮬레이션을 깨운다
        d.fx = d.x
        d.fy = d.y
        sim.alphaTarget(0.3).restart()
      })
      .on('drag', (event, d) => {
        d.fx = event.x
        d.fy = event.y
      })
      .on('end', (event, d) => {
        sim.alphaTarget(0)
        // 놓으면 다시 풀린다 ( 옵시디언처럼 )
        d.fx = null
        d.fy = null
        const end = clientPoint(event.sourceEvent as MouseEvent | TouchEvent)
        const start = dragOrigin.current
        if (start && Math.hypot(end.x - start.x, end.y - start.y) < CLICK_PX) onOpenRef.current(d.id, event.sourceEvent as OpenEvent)
      })
    nodeSel.call(dragBehavior)
    nodeSel
      .on('mouseenter', (_, d) => {
        hoverRef.current = d.id
        highlight()
      })
      .on('mouseleave', () => {
        hoverRef.current = null
        highlight()
      })

    sim.nodes(simNodes)
    ;(sim.force('link') as ForceLink<SimNode, SimLink>).links(simLinks)
    forcesRef.current?.()
    paint()
    highlight()
    sim.alpha(0.5).restart()
    return () => {
      sim.on('tick', null)
      highlightRef.current = null
    }
  }, [nodes, edges])

  // 힘 · 층 띠 설정이 바뀌면 시뮬레이션 힘과 배경 띠를 다시 맞춘다
  useEffect(() => {
    const sim = simRef.current!
    const applyForces = () => {
      const { width, height } = sizeRef.current
      const { layerPull: pull, distance: linkDistance, charge: push } = settingsRef.current
      ;(sim.force('link') as ForceLink<SimNode, SimLink>).distance(linkDistance)
      ;(sim.force('charge') as ReturnType<typeof forceManyBody<SimNode>>).strength(-push)
      ;(sim.force('collide') as ReturnType<typeof forceCollide<SimNode>>).radius((d) => d.radius + 4)
      ;(sim.force('x') as ReturnType<typeof forceX<SimNode>>).x(width / 2).strength(0.05)
      const forceYInstance = sim.force('y') as ReturnType<typeof forceY<SimNode>>
      if (pull) forceYInstance.y((d) => layerY(d.layer, height)).strength(0.25)
      else forceYInstance.y(height / 2).strength(0.05)
      // 층 끌림이 켜져 있으면 확대 · 이동 그룹 안 배경에 층마다 옅은 띠와 층 이름을 그린다
      const bands = select(svgRef.current!).select<SVGGElement>('g.fg-bands')
      bands
        .selectAll<SVGGElement, (typeof BANDS)[number]>('g')
        .data(pull ? [...BANDS] : [], (d) => d)
        .join((enter) => {
          const group = enter.append('g')
          group.append('rect')
          group.append('text')
          return group
        })
        .each(function (band) {
          const top = layerY(band, height) - height / 6
          select(this).select('rect').attr('x', -4000).attr('width', 8000 + width).attr('y', top).attr('height', height / 3).attr('fill', LAYER_COLOR[band]).attr('opacity', 0.06)
          select(this).select('text').text(band).attr('x', 12).attr('y', top + 20).attr('fill', LAYER_COLOR[band]).attr('font-size', 13).attr('font-weight', 700).attr('opacity', 0.7)
        })
    }
    forcesRef.current = applyForces
    applyForces()
    sim.alpha(0.5).restart()
  }, [layerPull, distance, charge])

  // 선택한 노트가 바뀌면 강조만 다시 그린다
  useEffect(() => {
    highlightRef.current?.()
  }, [selectedId])

  const fit = () => {
    const positions = [...positionsRef.current.values()]
    const behavior = zoomRef.current
    if (positions.length === 0 || !behavior) return
    const { width, height } = sizeRef.current
    const pad = 60
    const minX = Math.min(...positions.map((p) => p.x)) - pad
    const maxX = Math.max(...positions.map((p) => p.x)) + pad
    const minY = Math.min(...positions.map((p) => p.y)) - pad
    const maxY = Math.max(...positions.map((p) => p.y)) + pad
    const k = Math.min(3, Math.max(0.3, Math.min(width / (maxX - minX), height / (maxY - minY))))
    const tx = width / 2 - ((minX + maxX) / 2) * k
    const ty = height / 2 - ((minY + maxY) / 2) * k
    select(svgRef.current!).call(behavior.transform, zoomIdentity.translate(tx, ty).scale(k))
  }

  return (
    <div className="fg" ref={containerRef}>
      <svg ref={svgRef} className="fg-svg">
        <defs>
          <marker id="fg-arrow-upward" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" markerUnits="userSpaceOnUse" orient="auto">
            <path d="M0,0 L10,5 L0,10 z" fill={UPWARD_COLOR} />
          </marker>
          <marker id="fg-arrow-downward" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" markerUnits="userSpaceOnUse" orient="auto">
            <path d="M0,0 L10,5 L0,10 z" fill={DOWNWARD_COLOR} />
          </marker>
        </defs>
        <g className="fg-root">
          <g className="fg-bands" />
          <g className="fg-edges" />
          <g className="fg-flows" />
          <g className="fg-nodes" />
        </g>
      </svg>
      <button className="fg-fit" onClick={fit}>
        맞춤
      </button>
      <div className="fg-settings">
        <button className="fg-settings-head" aria-expanded={settingsOpen} onClick={() => setSettingsOpen((open) => !open)}>
          <span className="caret">{settingsOpen ? '▾' : '▸'}</span>설정
        </button>
        {settingsOpen && (
          <div className="fg-settings-body">
            <label>
              <input type="checkbox" checked={layerPull} onChange={(e) => setLayerPull(e.target.checked)} /> 층 끌림
            </label>
            <label>
              <input type="checkbox" checked={showSameLayer} onChange={(e) => onToggleSameLayer(e.target.checked)} /> 같은 층 링크 보기
            </label>
            <label>
              링크 거리 <span className="muted">{distance}</span>
              <input type="range" min={40} max={200} value={distance} onChange={(e) => setDistance(Number(e.target.value))} />
            </label>
            <label>
              밀어내는 힘 <span className="muted">{charge}</span>
              <input type="range" min={50} max={600} value={charge} onChange={(e) => setCharge(Number(e.target.value))} />
            </label>
          </div>
        )}
      </div>
      <div className="fg-legend">
        <div>
          <svg width="40" height="10"><line x1="0" y1="5" x2="40" y2="5" stroke={UPWARD_COLOR} strokeWidth="2" /></svg>
          상향 링크 ( 아래 → 위, 같은 층 포함 )
        </div>
        <div>
          <svg width="40" height="10">
            <line x1="0" y1="5" x2="40" y2="5" stroke={DOWNWARD_COLOR} strokeWidth="2" strokeDasharray="6 4" />
          </svg>
          열린 하향 조건부 링크 ( 위 → 아래 )
        </div>
        <div className="fg-legend-layers">
          {BANDS.map((layer) => (
            <span key={layer}>
              <span className="dot" style={{ background: LAYER_COLOR[layer] }} /> {layer}
            </span>
          ))}
        </div>
      </div>
    </div>
  )
}
