// 사용자 결정 2026-10-23 : 탐색기 폴더 트리는 서버 응답에 있는 노트만으로 만든다 - 층 › 그룹 › 노트
import type { ViewNote } from './api'
import { BANDS, type Band } from './layout'

// label 이 null 인 그룹은 전사 노트처럼 그룹이 없는 노트다
export type TreeGroup = { label: string | null; notes: ViewNote[] }
export type TreeLayer = { layer: Band; groups: TreeGroup[]; count: number }

function isBand(layer: string): layer is Band {
  return (BANDS as readonly string[]).includes(layer)
}

// 층 순서는 전사 · 팀 · 개인, 그룹은 이름순, 노트는 볼트에 들어온 순서 ( inserted_at_vault_size ) - 노트가 없는 층도 남긴다
export function buildTree(notes: ViewNote[]): TreeLayer[] {
  for (const note of notes) {
    // 층 순서에 없는 값은 어느 폴더에 둘지 알 수 없다
    if (!isBand(note.layer)) throw new Error(`알 수 없는 층 : ${note.layer} ( ${note.note_id} )`)
  }
  return BANDS.map((layer) => {
    const inLayer = notes.filter((note) => note.layer === layer)
    const byGroup = new Map<string | null, ViewNote[]>()
    for (const note of inLayer) {
      byGroup.set(note.group_label, [...(byGroup.get(note.group_label) ?? []), note])
    }
    const labels = [...byGroup.keys()].sort((a, b) => (a === null ? -1 : b === null ? 1 : a.localeCompare(b, 'ko')))
    const groups = labels.map((label) => ({
      label,
      notes: [...byGroup.get(label)!].sort(
        (a, b) => a.inserted_at_vault_size - b.inserted_at_vault_size || a.note_id.localeCompare(b.note_id),
      ),
    }))
    return { layer, groups, count: inLayer.length }
  })
}
