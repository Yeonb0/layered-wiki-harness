// 사용자 결정 2026-10-21 · 23 : 시연 경로 전용 화면 - "보는 사람 선택" 은 인증이 아니다
import type { Viewer, ViewersResponse } from './api'
import { LAYER_COLOR } from './colors'

const SECTIONS = ['개인', '팀', '전사'] as const

export function ViewerPicker({ data, onPick }: { data: ViewersResponse; onPick: (viewerId: string) => void }) {
  return (
    <div className="picker">
      <h1>보는 사람 선택 ( 시연용 · 인증 아님 ) - 합성 시연 코퍼스 ( 스냅샷 900 )</h1>
      {!data.show_names && <p className="notice warn">실제 코퍼스 실행 : 이름 · 본문이 가려짐</p>}
      {SECTIONS.map((layer) => {
        const items = data.viewers.filter((v) => v.layer === layer)
        return (
          <section key={layer}>
            <h2 style={{ color: LAYER_COLOR[layer] }}>
              {layer} ( {items.length} )
            </h2>
            <div className="cards">
              {items.map((viewer) => (
                <ViewerCard key={viewer.viewer_id} viewer={viewer} onPick={onPick} />
              ))}
            </div>
          </section>
        )
      })}
    </div>
  )
}

function ViewerCard({ viewer, onPick }: { viewer: Viewer; onPick: (viewerId: string) => void }) {
  return (
    <button className="card" style={{ borderColor: LAYER_COLOR[viewer.layer] }} onClick={() => onPick(viewer.viewer_id)}>
      <strong>{viewer.label}</strong>
      {viewer.layer === '개인' && <span>소속 팀 : {viewer.teams.join(' · ')}</span>}
    </button>
  )
}
