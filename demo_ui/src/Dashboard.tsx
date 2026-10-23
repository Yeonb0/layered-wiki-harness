// 사용자 결정 2026-10-23 : 대시보드는 두 모드의 보기를 모두 불러 두고 응답을 거르지 않고 세기만 한다
import type { Mode, ViewResponse } from './api'
import { LAYER_COLOR } from './colors'
import { BANDS } from './layout'
import { dashboardStats } from './stats'
import { MODE_LABEL } from './Sidebar'

export function Dashboard({
  mode,
  views,
}: {
  mode: Mode
  views: Record<Mode, { data: ViewResponse | null; error: string | null }>
}) {
  const current = views[mode]
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
    <div className="dashboard">
      <h1>대시보드 <span className="muted">( 지금 모드 : {MODE_LABEL[mode]} )</span></h1>
      <p className="notice warn">합성 시연 코퍼스의 메커니즘 시연이며 측정 결과가 아니다</p>
      <div className="cards-row">
        {cards.map((card) => (
          <div key={card.label} className="stat">
            <div className="stat-value">{card.value}</div>
            <div className="stat-label">{card.label}</div>
          </div>
        ))}
      </div>
      <h2>두 모드 비교 ( 층별 보이는 노트 수 )</h2>
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
    </div>
  )
}
