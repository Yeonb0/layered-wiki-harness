// 사용자 결정 2026-10-23 : 대시보드는 노션 느낌 ( 데이터베이스 표 · 보드 · 토글 ). 두 모드의 보기를 모두 불러 두고 응답을 거르지 않고 세기만 한다
// 정렬 · 거르기는 서버가 거른 보기 안에서만 하는 화면 표시다
import { useMemo, useState } from 'react'
import type { Mode, Viewer, ViewResponse } from './api'
import { LAYER_COLOR } from './colors'
import { boardColumns, filterByLayer, sortRows, toRows, type Row, type SortKey } from './database'
import { BANDS } from './layout'
import { MARKER_KIND_LABEL } from './markers'
import { dashboardStats } from './stats'
import { MODE_LABEL } from './Sidebar'
import { Toggle } from './Toggle'
import type { OpenEvent } from './tabs'

type ModeView = { data: ViewResponse | null; error: string | null }

const COLUMNS: { key: SortKey; label: string }[] = [
  { key: 'title', label: '제목' },
  { key: 'layer', label: '층' },
  { key: 'group', label: '그룹' },
  { key: 'sourceDoc', label: '출처 문서' },
  { key: 'segments', label: '세그먼트' },
  { key: 'upward', label: '상향' },
  { key: 'openedDown', label: '열린 하향' },
  { key: 'markers', label: '표지' },
]

function MarkerBadges({ row }: { row: Row }) {
  if (row.markers.length === 0) return null
  return (
    <>
      {row.markers.map((marker) => (
        <span key={marker.text} className={`kind kind-${marker.kind}`} title={MARKER_KIND_LABEL[marker.kind]}>
          {marker.text}
        </span>
      ))}
    </>
  )
}

function Database({ rows, onOpenNote }: { rows: Row[]; onOpenNote: (noteId: string, ev?: OpenEvent) => void }) {
  const [viewKind, setViewKind] = useState<'table' | 'board'>('table')
  const [layers, setLayers] = useState<Set<string>>(new Set())
  const [sort, setSort] = useState<{ key: SortKey; dir: 'asc' | 'desc' }>({ key: 'title', dir: 'asc' })
  const shown = useMemo(() => sortRows(filterByLayer(rows, layers), sort.key, sort.dir), [rows, layers, sort])
  const columns = useMemo(() => boardColumns(shown), [shown])
  const toggleLayer = (layer: string) =>
    setLayers((prev) => {
      const next = new Set(prev)
      if (next.has(layer)) next.delete(layer)
      else next.add(layer)
      return next
    })
  const clickHeader = (key: SortKey) =>
    setSort((prev) => (prev.key === key ? { key, dir: prev.dir === 'asc' ? 'desc' : 'asc' } : { key, dir: 'asc' }))
  return (
    <div className="db">
      <div className="db-tabs">
        <button className={viewKind === 'table' ? 'db-tab on' : 'db-tab'} onClick={() => setViewKind('table')}>
          표
        </button>
        <button className={viewKind === 'board' ? 'db-tab on' : 'db-tab'} onClick={() => setViewKind('board')}>
          보드
        </button>
      </div>
      <div className="db-chips">
        {BANDS.map((layer) => (
          <button
            key={layer}
            className={layers.has(layer) ? 'chip-filter on' : 'chip-filter'}
            style={layers.has(layer) ? { borderColor: LAYER_COLOR[layer] } : undefined}
            onClick={() => toggleLayer(layer)}
          >
            <span className="dot" style={{ background: LAYER_COLOR[layer] }} />
            {layer}
          </button>
        ))}
      </div>
      {viewKind === 'table' ? (
        <table className="db-table">
          <thead>
            <tr>
              {COLUMNS.map((column) => (
                <th key={column.key} onClick={() => clickHeader(column.key)}>
                  {column.label}
                  {sort.key === column.key ? (sort.dir === 'asc' ? ' ↑' : ' ↓') : ''}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {shown.map((row) => (
              <tr key={row.noteId} onClick={(e) => onOpenNote(row.noteId, e)} onAuxClick={(e) => e.button === 1 && onOpenNote(row.noteId, e)}>
                <td className="db-title">{row.title}</td>
                <td>
                  <span className="badge" style={{ background: LAYER_COLOR[row.layer] }}>{row.layer}</span>
                </td>
                <td>{row.group ?? <span className="muted">없음</span>}</td>
                <td className="mono">{row.sourceDoc}</td>
                <td>{row.segments}</td>
                <td>{row.upward}</td>
                <td>{row.openedDown}</td>
                <td>
                  <MarkerBadges row={row} />
                </td>
              </tr>
            ))}
            {shown.length === 0 && (
              <tr>
                <td colSpan={COLUMNS.length} className="muted">
                  보이는 노트 없음
                </td>
              </tr>
            )}
          </tbody>
        </table>
      ) : (
        <div className="board">
          {BANDS.map((layer) => (
            <div key={layer} className="board-col">
              <div className="board-head">
                <span className="dot" style={{ background: LAYER_COLOR[layer] }} />
                {layer} <span className="muted">{columns[layer].length}</span>
              </div>
              {columns[layer].length === 0 && <p className="muted">보이는 노트 없음</p>}
              {columns[layer].map((row) => (
                <button
                  key={row.noteId}
                  className="board-card"
                  onClick={(e) => onOpenNote(row.noteId, e)}
                  onAuxClick={(e) => e.button === 1 && onOpenNote(row.noteId, e)}
                >
                  <div className="board-title">{row.title}</div>
                  {row.group && <span className="tag">{row.group}</span>}
                  <div className="muted board-meta">{`상향 ${row.upward} · 열린 하향 ${row.openedDown}`}</div>
                  <div>
                    <MarkerBadges row={row} />
                  </div>
                </button>
              ))}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

export function Dashboard({
  mode,
  views,
  viewer,
  showNames,
  onOpenNote,
}: {
  mode: Mode
  views: Record<Mode, ModeView>
  viewer: Viewer
  showNames: boolean
  onOpenNote: (noteId: string, ev?: OpenEvent) => void
}) {
  const current = views[mode]
  const rows = useMemo(() => (current.data ? toRows(current.data, showNames) : []), [current.data, showNames])
  if (current.error) return <div className="notice error">오류 : {current.error}</div>
  if (!current.data) return <div className="notice">불러오는 중</div>
  const stats = dashboardStats(current.data)
  const cards: { label: string; value: number | string }[] = [
    { label: '보이는 노트', value: stats.totalNotes },
    ...BANDS.map((layer) => ({ label: `${layer} 노트`, value: stats.notesByLayer[layer] })),
    { label: '보이는 상향 링크', value: stats.upwardLinks },
    { label: '열린 하향 조건부 링크', value: stats.openedDownward },
    { label: '가려진 하향 조건부 링크', value: stats.hiddenDownward },
    { label: '가려진 상향 링크', value: stats.hiddenUpward },
  ]
  const modes = Object.keys(MODE_LABEL) as Mode[]
  const loaded = modes.map((m) => ({ mode: m, stats: views[m].data ? dashboardStats(views[m].data!) : null }))
  const max = Math.max(1, ...loaded.flatMap((item) => (item.stats ? BANDS.map((layer) => item.stats!.notesByLayer[layer]) : [0])))
  return (
    <div className="page">
      <h1>대시보드</h1>
      <p className="subtitle">{`${viewer.label} ( ${viewer.layer} ) · ${MODE_LABEL[mode]}`}</p>
      <p className="notice warn">합성 시연 코퍼스의 메커니즘 시연이며 측정 결과가 아니다</p>
      <Toggle title="요약">
        <div className="cards-row">
          {cards.map((card) => (
            <div key={card.label} className="stat">
              <div className="stat-value">{card.value}</div>
              <div className="stat-label">{card.label}</div>
            </div>
          ))}
        </div>
      </Toggle>
      <Toggle title="두 모드 비교">
        <div className="bars">
          {BANDS.map((layer) => (
            <div key={layer} className="bar-group">
              <div className="bar-title" style={{ color: LAYER_COLOR[layer] }}>{layer}</div>
              {loaded.map((item) => (
                <div key={item.mode} className="bar-row">
                  <span className="bar-mode">{MODE_LABEL[item.mode]}</span>
                  <span className="bar-track">
                    <span
                      className="bar-fill"
                      style={{ width: `${item.stats ? (item.stats.notesByLayer[layer] / max) * 100 : 0}%`, background: LAYER_COLOR[layer] }}
                    />
                  </span>
                  <span className="bar-num">{item.stats ? item.stats.notesByLayer[layer] : '…'}</span>
                </div>
              ))}
            </div>
          ))}
        </div>
      </Toggle>
      <Toggle title="노트 데이터베이스">
        <Database rows={rows} onOpenNote={onOpenNote} />
      </Toggle>
    </div>
  )
}
