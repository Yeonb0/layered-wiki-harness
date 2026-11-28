// 사용자 결정 2026-10-23 : 대시보드는 노션 느낌 ( 데이터베이스 표 · 보드 · 토글 ). 두 모드의 보기를 모두 불러 두고 응답을 거르지 않고 세기만 한다
// 정렬 · 거르기는 서버가 거른 보기 안에서만 하는 화면 표시다
import { useEffect, useMemo, useState, type CSSProperties } from 'react'
import { fetchHealth, type Mode, type Viewer, type ViewResponse } from './api'
import { LAYER_COLOR } from './colors'
import { boardColumns, filterByLayer, sortRows, toRows, type Row, type SortKey } from './database'
import { BANDS } from './layout'
import { MARKER_KIND_LABEL } from './markers'
import { modelNotice } from './front'
import { dashboardStats, largestLayer, layerDeltas } from './stats'
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

// 숫자 열은 오른쪽 정렬해 자릿수를 맞춘다
const NUMERIC = new Set<SortKey>(['segments', 'upward', 'openedDown'])

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
  // 사용자 요청 2026-11-28 : 표지가 하나도 없으면 빈 칸이 되므로 표지 열을 뺀다
  const hasMarkers = useMemo(() => rows.some((row) => row.markers.length > 0), [rows])
  const visibleColumns = hasMarkers ? COLUMNS : COLUMNS.filter((column) => column.key !== 'markers')
  const layerCount = (layer: string) => rows.filter((row) => row.layer === layer).length
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
            {`${layer} ${layerCount(layer)}`}
          </button>
        ))}
      </div>
      {viewKind === 'table' ? (
        <table className="db-table">
          <thead>
            <tr>
              {visibleColumns.map((column) => (
                <th key={column.key} className={NUMERIC.has(column.key) ? 'num' : undefined} onClick={() => clickHeader(column.key)}>
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
                <td>{row.group ?? <span className="muted" aria-label="그룹 없음">—</span>}</td>
                <td className="num-text">{row.sourceDoc}</td>
                <td className="num">{row.segments}</td>
                <td className={row.upward === 0 ? 'num muted' : 'num'}>{row.upward}</td>
                <td className={row.openedDown === 0 ? 'num muted' : 'num opened'}>{row.openedDown}</td>
                {hasMarkers && (
                  <td>
                    <MarkerBadges row={row} />
                  </td>
                )}
              </tr>
            ))}
            {shown.length === 0 && (
              <tr>
                <td colSpan={visibleColumns.length} className="muted">
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
  // AI 사용 고지 : 서버가 쓰는 모델을 경고 줄에 붙인다 (옛 서버는 model_id 가 없어 붙이지 않는다)
  const [notice, setNotice] = useState<string | null>(null)
  useEffect(() => {
    let cancelled = false
    fetchHealth()
      .then((health) => !cancelled && setNotice(modelNotice(health)))
      .catch(() => {})
    return () => {
      cancelled = true
    }
  }, [])
  if (current.error) return <div className="notice error">오류 : {current.error}</div>
  if (!current.data) return <div className="notice">불러오는 중</div>
  const stats = dashboardStats(current.data)
  const modes = Object.keys(MODE_LABEL) as Mode[]
  const loaded = modes.map((m) => ({ mode: m, stats: views[m].data ? dashboardStats(views[m].data!) : null }))
  const max = Math.max(1, ...loaded.flatMap((item) => (item.stats ? BANDS.map((layer) => item.stats!.notesByLayer[layer]) : [0])))
  // 사용자 요청 2026-11-28 : 대시보드 가독성 개선 - 숫자 카드 7개 대신 한 문장 요약 · 층 띠 · 모드별 증감
  const largest = largestLayer(stats.notesByLayer)
  const conditionalTotal = stats.openedDownward + stats.hiddenDownward
  const [first, second] = loaded
  const deltas = first.stats && second.stats ? layerDeltas(first.stats.notesByLayer, second.stats.notesByLayer) : null
  return (
    <div className="page">
      <p className="demo-strip">
        <strong>시연 화면</strong>
        <span>합성 시연 코퍼스의 메커니즘 시연이며 측정 결과가 아니다</span>
        {notice && (
          <details>
            <summary>실행 정보</summary>
            {notice}
          </details>
        )}
      </p>
      <h1>{`${viewer.label} 에게 보이는 볼트`}</h1>
      <p className="subtitle">{`${viewer.layer} · ${MODE_LABEL[mode]}`}</p>
      <p className="lead">
        노트 <b>{stats.totalNotes}개</b>
        {largest && (
          <>
            , 그중 {largest.layer} 노트가 <b>{largest.count}개</b>
          </>
        )}
        입니다.{' '}
        {conditionalTotal > 0 ? (
          <>
            하향 조건부 링크 {conditionalTotal}개 중 <b>{stats.openedDownward}개가 열려</b> 있고 {stats.hiddenDownward}개는 가려져 있습니다.
          </>
        ) : (
          '하향 조건부 링크는 없습니다.'
        )}
      </p>
      <Toggle title="층별 노트와 링크">
        <p className="section-sub">위가 전사, 아래가 개인입니다. 상향 링크는 아래에서 위로, 하향 조건부 링크는 조건이 맞을 때만 열립니다.</p>
        <div className="strata">
          <div className="strata-bands">
            {BANDS.map((layer) => (
              <div key={layer} className="band" style={{ '--layer': LAYER_COLOR[layer] } as CSSProperties}>
                <span className="band-name">{layer}</span>
                <span className="band-count">{stats.notesByLayer[layer]}</span>
                {stats.notesByLayer[layer] === 0 ? (
                  <span className="muted">보이는 노트 없음</span>
                ) : (
                  <span className="band-chips" aria-hidden="true">
                    {Array.from({ length: stats.notesByLayer[layer] }, (_, i) => (
                      <i key={i} />
                    ))}
                  </span>
                )}
              </div>
            ))}
          </div>
          <dl className="strata-links">
            <div>
              <dt>상향 링크</dt>
              <dd>
                {stats.upwardLinks} <span>보임 / 가려짐 {stats.hiddenUpward}</span>
              </dd>
            </div>
            <div>
              <dt>하향 조건부 링크</dt>
              <dd>
                {stats.openedDownward} <span>열림 / 가려짐 {stats.hiddenDownward}</span>
              </dd>
            </div>
          </dl>
        </div>
      </Toggle>
      <Toggle title="두 모드에서 달라지는 것">
        <p className="section-sub">같은 보는 사람, 같은 원본 문서로 만든 두 볼트의 층별 노트 수입니다.</p>
        <div className="compare-rows">
          {BANDS.map((layer) => {
            const delta = deltas ? deltas[layer] : null
            return (
              <div key={layer} className="compare-row">
                <span className="compare-layer" style={{ color: LAYER_COLOR[layer] }}>{layer}</span>
                <div className="bars">
                  {loaded.map((item, index) => (
                    <div key={item.mode} className={index === 0 ? 'bar-row' : 'bar-row second'}>
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
                {delta === null ? (
                  <span className="delta muted">…</span>
                ) : delta === 0 ? (
                  <span className="delta muted">변화 없음</span>
                ) : (
                  <span className="delta" style={{ color: LAYER_COLOR[layer] }}>
                    {delta > 0 ? `+${delta}` : `−${-delta}`}
                    <small>{`${MODE_LABEL[second.mode]}에서`}</small>
                  </span>
                )}
              </div>
            )
          })}
        </div>
      </Toggle>
      <Toggle title="노트 목록">
        <Database rows={rows} onOpenNote={onOpenNote} />
      </Toggle>
    </div>
  )
}
