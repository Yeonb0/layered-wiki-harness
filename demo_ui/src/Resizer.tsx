// 사용자 요청 2026-10-23 : 탐색기 · 연결 패널 폭을 끌어서 바꾼다 - 손잡이는 끌기 · 더블클릭 초기화 · 방향키를 받는다
// 사용자 요청 2026-10-23 : 폭을 많이 줄이려 끌면 접히고, 접힌 손잡이는 누르거나 펴는 방향으로 끌면 마지막 폭으로 펴진다
import { useRef, type KeyboardEvent, type PointerEvent } from 'react'
import { clampWidth, PANEL_LIMITS, shouldCollapse, type Panel } from './panelWidth'

const LABEL: Record<Panel, string> = { sidebar: '탐색기 폭', connections: '연결 패널 폭' }
const EXPAND_LABEL: Record<Panel, string> = { sidebar: '탐색기 펴기', connections: '연결 패널 펴기' }
// 접힌 손잡이를 이만큼 움직이면 클릭이 아니라 끌기로 본다 - 펴는 방향이면 펴고, 반대면 아무 일도 하지 않는다
const CLICK_PX = 4
// 방향키 한 번에 바꾸는 폭
const KEY_STEP = 16

export function Resizer({
  panel,
  width,
  onChange,
  onCommit,
  direction,
  collapsed,
  onCollapse,
  onExpand,
}: {
  panel: Panel
  width: number
  onChange: (px: number) => void
  onCommit: () => void
  // 탐색기 오른쪽 손잡이는 오른쪽으로 끌면 넓어진다 ( 1 ), 연결 패널 왼쪽 손잡이는 왼쪽으로 끌면 넓어진다 ( -1 )
  direction: 1 | -1
  collapsed: boolean
  onCollapse: () => void
  onExpand: () => void
}) {
  const start = useRef<{ x: number; width: number } | null>(null)
  const limits = PANEL_LIMITS[panel]

  const onPointerDown = (event: PointerEvent<HTMLDivElement>) => {
    event.currentTarget.setPointerCapture(event.pointerId)
    start.current = { x: event.clientX, width }
    document.body.classList.add('resizing')
  }
  const onPointerMove = (event: PointerEvent<HTMLDivElement>) => {
    if (!start.current) return
    const raw = start.current.width + direction * (event.clientX - start.current.x)
    if (collapsed) {
      // 접힌 손잡이는 펴는 방향으로 끌면 펴고 끌기를 끝낸다
      if (direction * (event.clientX - start.current.x) > CLICK_PX) {
        start.current = null
        document.body.classList.remove('resizing')
        onExpand()
      }
      return
    }
    // 클램프 전 원시 폭이 접을 만큼 작으면 접고 끌기를 끝낸다
    if (shouldCollapse(panel, raw)) {
      start.current = null
      document.body.classList.remove('resizing')
      onCollapse()
      return
    }
    onChange(clampWidth(panel, raw))
  }
  const finish = (event: PointerEvent<HTMLDivElement>) => {
    const origin = start.current
    if (!origin) return
    start.current = null
    document.body.classList.remove('resizing')
    if (collapsed) {
      // 움직임이 거의 없으면 클릭이다
      if (Math.abs(event.clientX - origin.x) <= CLICK_PX) onExpand()
      return
    }
    onCommit()
  }
  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    // 접힌 손잡이는 Enter · Space 로 편다 - 폭 조절 키는 펼친 상태에서만 받는다
    if (collapsed) {
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault()
        onExpand()
      }
      return
    }
    if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return
    event.preventDefault()
    const sign = event.key === 'ArrowRight' ? 1 : -1
    onChange(clampWidth(panel, width + direction * sign * KEY_STEP))
    onCommit()
  }
  return (
    <div
      className={collapsed ? 'resizer collapsed' : 'resizer'}
      role="separator"
      aria-orientation="vertical"
      aria-label={collapsed ? EXPAND_LABEL[panel] : LABEL[panel]}
      aria-expanded={!collapsed}
      aria-valuenow={collapsed ? 0 : width}
      aria-valuemin={limits.min}
      aria-valuemax={limits.max}
      tabIndex={0}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={finish}
      onPointerCancel={finish}
      onDoubleClick={() => {
        // 더블클릭 초기화는 펼친 상태에서만 한다
        if (collapsed) return
        onChange(limits.initial)
        onCommit()
      }}
      onKeyDown={onKeyDown}
    />
  )
}
