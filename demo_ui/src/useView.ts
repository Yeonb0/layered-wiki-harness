// 사용자 결정 2026-10-21 · 23 : 시연 경로 전용 화면 - 보는 사람 · 모드별 보기를 서버에서 받아 그대로 돌려준다
import { useEffect, useState } from 'react'
import { fetchView, type Mode, type ViewResponse } from './api'

export function useView(mode: Mode, viewerId: string): { data: ViewResponse | null; error: string | null } {
  const [data, setData] = useState<ViewResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    let cancelled = false
    setData(null)
    setError(null)
    fetchView(mode, viewerId)
      .then((response) => {
        if (!cancelled) setData(response)
      })
      .catch((e: unknown) => {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e))
      })
    return () => {
      cancelled = true
    }
  }, [mode, viewerId])
  return { data, error }
}
