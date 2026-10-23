// 사용자 요청 2026-10-23 : 탐색기 · 연결 패널 폭을 끌어서 바꾼다 - 손잡이는 끌기 · 더블클릭 초기화 · 방향키를 받는다
import { useRef, type KeyboardEvent, type PointerEvent } from 'react'
import { clampWidth, PANEL_LIMITS, type Panel } from './panelWidth'

const LABEL: Record<Panel, string> = { sidebar: '탐색기 폭', connections: '연결 패널 폭' }
// 방향키 한 번에 바꾸는 폭
const KEY_STEP = 16

export function Resizer({
  panel,
  width,
  onChange,
  onCommit,
  direction,
}: {
  panel: Panel
  width: number
  onChange: (px: number) => void
  onCommit: () => void
  // 탐색기 오른쪽 손잡이는 오른쪽으로 끌면 넓어진다 ( 1 ), 연결 패널 왼쪽 손잡이는 왼쪽으로 끌면 넓어진다 ( -1 )
  direction: 1 | -1
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
    onChange(clampWidth(panel, start.current.width + direction * (event.clientX - start.current.x)))
  }
  const finish = () => {
    if (!start.current) return
    start.current = null
    document.body.classList.remove('resizing')
    onCommit()
  }
  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return
    event.preventDefault()
    const sign = event.key === 'ArrowRight' ? 1 : -1
    onChange(clampWidth(panel, width + direction * sign * KEY_STEP))
    onCommit()
  }
  return (
    <div
      className="resizer"
      role="separator"
      aria-orientation="vertical"
      aria-label={LABEL[panel]}
      aria-valuenow={width}
      aria-valuemin={limits.min}
      aria-valuemax={limits.max}
      tabIndex={0}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={finish}
      onPointerCancel={finish}
      onDoubleClick={() => {
        onChange(limits.initial)
        onCommit()
      }}
      onKeyDown={onKeyDown}
    />
  )
}
