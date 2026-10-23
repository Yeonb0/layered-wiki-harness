// 사용자 결정 2026-10-23 : 비교 화면은 서버가 거른 두 결과를 나누기만 한다 - 화면이 노트를 거르지 않는다
import type { ViewNote, ViewResponse } from './api'
import { BANDS } from './layout'

function order(note: ViewNote): number {
  const index = (BANDS as readonly string[]).indexOf(note.layer)
  // 층 순서에 없는 값은 어느 칸에 놓을지 알 수 없다
  if (index < 0) throw new Error(`알 수 없는 층 : ${note.layer} ( ${note.note_id} )`)
  return index
}

// 층 ( 전사 → 팀 → 개인 ) 다음 제목 순
function sorted(notes: ViewNote[]): ViewNote[] {
  return [...notes].sort((a, b) => order(a) - order(b) || a.title.localeCompare(b.title, 'ko'))
}

export function compareViews(a: ViewResponse, b: ViewResponse): { both: ViewNote[]; onlyA: ViewNote[]; onlyB: ViewNote[] } {
  // 모드가 다르면 볼트가 달라 note_id 대조가 무의미하다
  if (a.mode !== b.mode) throw new Error(`모드가 다른 보기는 비교하지 않는다 : ${a.mode} / ${b.mode}`)
  const idsB = new Set(b.notes.map((note) => note.note_id))
  const idsA = new Set(a.notes.map((note) => note.note_id))
  return {
    // both 에는 a 쪽 노트를 넣는다
    both: sorted(a.notes.filter((note) => idsB.has(note.note_id))),
    onlyA: sorted(a.notes.filter((note) => !idsB.has(note.note_id))),
    onlyB: sorted(b.notes.filter((note) => !idsA.has(note.note_id))),
  }
}
