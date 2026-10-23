// 사용자 결정 2026-10-23 : 대시보드 숫자는 응답을 거르지 않고 세기만 한다 - 서버가 보낸 것이 그대로 센다
import type { ViewResponse } from './api'
import { BANDS, type Band } from './layout'

export type DashboardStats = {
  notesByLayer: Record<Band, number>
  totalNotes: number
  upwardLinks: number
  openedDownward: number
  hiddenDownward: number
  hiddenUpward: number
}

export function dashboardStats(view: ViewResponse): DashboardStats {
  const notesByLayer = { 전사: 0, 팀: 0, 개인: 0 } as Record<Band, number>
  let upwardLinks = 0
  let openedDownward = 0
  for (const note of view.notes) {
    // 층 순서에 없는 값은 어느 칸에 셀지 알 수 없다
    if (!(BANDS as readonly string[]).includes(note.layer)) {
      throw new Error(`알 수 없는 층 : ${note.layer} ( ${note.note_id} )`)
    }
    notesByLayer[note.layer as Band] += 1
    upwardLinks += note.upward_links.length
    openedDownward += note.opened_downward_links.length
  }
  return {
    notesByLayer,
    totalNotes: view.notes.length,
    upwardLinks,
    openedDownward,
    // 가려진 링크는 서버가 센 값을 그대로 쓴다 - 응답에 없는 링크는 화면이 셀 수 없다
    hiddenDownward: view.counts.conditional_links_hidden,
    hiddenUpward: view.counts.upward_links_hidden,
  }
}
