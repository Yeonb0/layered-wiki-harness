// 사용자 결정 2026-10-21 · 23 : 시연 경로 전용 화면 - 보는 사람 · 모드별 보기를 서버에서 받아 그대로 돌려준다
import { useEffect, useState } from 'react'
import { fetchView, type Mode, type ViewResponse } from './api'

// viewerId 가 null 이면 요청하지 않는다 - 비교할 보는 사람을 고르기 전 상태
// jobId 가 있으면 그 작업의 새 노트를 겹친 보기를 받는다 - jobId 가 바뀌어도 다시 불러온다
export function useView(
  mode: Mode,
  viewerId: string | null,
  jobId?: string | null,
): { data: ViewResponse | null; error: string | null } {
  const [data, setData] = useState<ViewResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    let cancelled = false
    setData(null)
    setError(null)
    if (viewerId === null) return
    fetchView(mode, viewerId, jobId)
      .then((response) => {
        if (!cancelled) setData(response)
      })
      .catch((e: unknown) => {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e))
      })
    return () => {
      cancelled = true
    }
  }, [mode, viewerId, jobId])
  return { data, error }
}
