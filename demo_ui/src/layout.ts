// 사용자 결정 2026-10-21 · 23 : 시연 경로 전용 화면 - 노트의 층 · 칸 배치를 순수 함수로 계산한다
import type { ViewNote } from './api'

// 위에서 아래 순서 : 전사 → 팀 → 개인
export const BANDS = ['전사', '팀', '개인'] as const
export type Band = (typeof BANDS)[number]

export const NODE_W = 220
export const NODE_H = 76
const GAP = 20
const PAD = 16
const LABEL_H = 28
// 띠 이름은 띠 왼쪽 위 한 줄에 두고 칸은 그 아래에서 시작한다 - 띠 이름과 칸 이름이 겹치지 않게
const BAND_LABEL_H = 28
const BAND_GAP = 40
const MIN_BAND_H = 96
// 칸 안에서 한 줄에 놓는 노드 수
const PER_ROW = 2

export type LaidOutNode = { note: ViewNote; band: Band; cell: string; x: number; y: number }
export type CellBox = { band: Band; label: string; x: number; y: number; width: number; height: number }
// empty : 이 보기에서 보이는 노트가 없는 띠 - 화면이 안내 문구를 보인다
export type BandBox = { band: Band; y: number; height: number; empty: boolean }
export type Layout = { nodes: LaidOutNode[]; cells: CellBox[]; bands: BandBox[]; width: number; height: number }

function isBand(layer: string): layer is Band {
  return (BANDS as readonly string[]).includes(layer)
}

// 층마다 칸 이름 : 팀 띠는 팀 이름, 개인 띠는 주인 이름, 전사는 그룹이 없어 층 이름
export function cellLabel(note: ViewNote): string {
  return note.group_label ?? note.layer
}

export function layoutNotes(notes: ViewNote[]): Layout {
  for (const note of notes) {
    // 층 순서에 없는 값은 어느 띠에 놓을지 알 수 없다
    if (!isBand(note.layer)) {
      throw new Error(`알 수 없는 층 : ${note.layer} ( ${note.note_id} )`)
    }
  }
  const nodes: LaidOutNode[] = []
  const cells: CellBox[] = []
  const bands: BandBox[] = []
  let y = 0
  let width = 0
  for (const band of BANDS) {
    const groups = new Map<string, ViewNote[]>()
    for (const note of notes.filter((n) => n.layer === band)) {
      const label = cellLabel(note)
      groups.set(label, [...(groups.get(label) ?? []), note])
    }
    const labels = [...groups.keys()].sort((a, b) => a.localeCompare(b, 'ko'))
    const rows = Math.max(0, ...labels.map((label) => Math.ceil(groups.get(label)!.length / PER_ROW)))
    const height = rows === 0 ? MIN_BAND_H : BAND_LABEL_H + LABEL_H + PAD * 2 + rows * (NODE_H + GAP) - GAP
    const cellsY = y + BAND_LABEL_H
    let x = 0
    for (const label of labels) {
      // 칸 안에서는 볼트에 들어온 순서 ( inserted_at_vault_size ) 로 놓는다
      const ordered = [...groups.get(label)!].sort(
        (a, b) => a.inserted_at_vault_size - b.inserted_at_vault_size || a.note_id.localeCompare(b.note_id),
      )
      const columns = Math.min(ordered.length, PER_ROW)
      const cellWidth = PAD * 2 + columns * NODE_W + (columns - 1) * GAP
      ordered.forEach((note, index) => {
        nodes.push({
          note,
          band,
          cell: label,
          x: x + PAD + (index % PER_ROW) * (NODE_W + GAP),
          y: cellsY + LABEL_H + PAD + Math.floor(index / PER_ROW) * (NODE_H + GAP),
        })
      })
      cells.push({ band, label, x, y: cellsY, width: cellWidth, height: height - BAND_LABEL_H })
      x += cellWidth + GAP
    }
    bands.push({ band, y, height, empty: labels.length === 0 })
    width = Math.max(width, x)
    y += height + BAND_GAP
  }
  return { nodes, cells, bands, width, height: y - BAND_GAP }
}
