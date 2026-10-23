// 사용자 결정 2026-10-21 · 23 : 시연 경로 전용 화면 - 보는 사람 선택은 인증이 아니고 서버가 보는 사람별로 거른 결과만 그린다
import { useEffect, useState } from 'react'
import { fetchHealth, fetchViewers, type ViewersResponse } from './api'
import { ViewerPicker } from './ViewerPicker'
import { Workspace } from './Workspace'

export default function App() {
  const [viewers, setViewers] = useState<ViewersResponse | null>(null)
  const [baseRun, setBaseRun] = useState<string | null>(null)
  const [viewerId, setViewerId] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    fetchViewers()
      .then((response) => {
        if (!cancelled) setViewers(response)
      })
      .catch((e: unknown) => {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e))
      })
    // 상태 막대에만 쓰는 값이라 실패해도 화면은 계속 쓴다
    fetchHealth()
      .then((response) => {
        if (!cancelled) setBaseRun(response.base_run)
      })
      .catch(() => undefined)
    return () => {
      cancelled = true
    }
  }, [])

  if (error) return <div className="notice error">오류 : {error}</div>
  if (!viewers) return <div className="notice">보는 사람 목록을 불러오는 중</div>
  const viewer = viewers.viewers.find((v) => v.viewer_id === viewerId)
  if (!viewer) return <ViewerPicker data={viewers} onPick={setViewerId} />
  return (
    <Workspace
      key={viewer.viewer_id}
      viewer={viewer}
      viewers={viewers.viewers}
      showNames={viewers.show_names}
      baseRun={baseRun}
      onChangeViewer={() => setViewerId(null)}
    />
  )
}
