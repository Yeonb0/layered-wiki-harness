// 사용자 결정 2026-10-23 : 모드 비교 + 누출 표지 - 지금 보는 사람의 두 모드 보기를 표지 표로 나란히 놓는다
// 지침 3절 19 · 20 : 시연 결과는 측정 결과가 아니다 - 표지는 합성 문서에 일부러 심은 것이다
import { useMemo } from 'react'
import type { Mode, ViewNote, ViewResponse } from './api'
import { LAYER_COLOR } from './colors'
import { findMarkers, MARKER_KIND_LABEL, MARKERS, type MarkerKind } from './markers'
import { MODE_LABEL } from './Sidebar'
import type { OpenEvent } from './tabs'

type ModeView = { data: ViewResponse | null; error: string | null }
const MODES = Object.keys(MODE_LABEL) as Mode[]
const KINDS: MarkerKind[] = ['up', 'cross', 'home', 'down']

type Hit = { note: ViewNote; kind: MarkerKind; count: number }

export function CompareMode({
  views,
  showNames,
  onOpenNoteInMode,
}: {
  views: Record<Mode, ModeView>
  showNames: boolean
  onOpenNoteInMode: (mode: Mode, noteId: string, ev?: OpenEvent) => void
}) {
  // 표지 판정은 모드별로 응답 노트의 제목과 본문에서 찾는다 - 본문이 가려진 실행에서는 하지 않는다
  const hits = useMemo(() => {
    const out = {} as Record<Mode, Map<string, Hit[]>>
    for (const mode of MODES) {
      const map = new Map<string, Hit[]>()
      for (const note of showNames ? (views[mode].data?.notes ?? []) : []) {
        for (const found of findMarkers(note)) {
          map.set(found.marker.text, [...(map.get(found.marker.text) ?? []), { note, kind: found.kind, count: found.count }])
        }
      }
      out[mode] = map
    }
    return out
  }, [views, showNames])

  if (!showNames) {
    return (
      <div className="cmp">
        <h1>모드 비교 + 누출 표지</h1>
        <p className="notice warn">이름 · 본문이 가려진 실행에서는 표지를 판정하지 않는다</p>
      </div>
    )
  }
  const error = MODES.map((m) => views[m].error).find((e) => e)
  if (error) return <div className="notice error">오류 : {error}</div>
  if (MODES.some((m) => !views[m].data)) return <div className="notice">불러오는 중</div>

  // 노트 × 표지 단위로 센다 - 한 노트에 같은 표지가 여러 번 있어도 1 건이다
  const summary = (mode: Mode) => {
    const counts: Record<MarkerKind, number> = { up: 0, cross: 0, home: 0, down: 0 }
    for (const list of hits[mode].values()) for (const hit of list) counts[hit.kind] += 1
    return counts
  }
  return (
    <div className="cmp">
      <h1>모드 비교 + 누출 표지</h1>
      <p className="notice warn">{`합성 표지 ${MARKERS.length}개의 정확 일치만 센다. 메커니즘 시연이며 측정 결과가 아니다`}</p>
      <div className="mk-summary">
        {MODES.map((mode) => {
          const counts = summary(mode)
          return (
            <div key={mode} className="stat">
              <div className="stat-label">{MODE_LABEL[mode]} ( 노트 × 표지 )</div>
              <div className="mk-counts">
                {KINDS.map((kind) => (
                  <span key={kind} className={`kind kind-${kind}`}>
                    {MARKER_KIND_LABEL[kind]} <b>{counts[kind]}</b>
                  </span>
                ))}
              </div>
            </div>
          )
        })}
      </div>
      <table className="mk-table">
        <thead>
          <tr>
            <th>표지</th>
            <th>출처</th>
            {MODES.map((mode) => (
              <th key={mode}>{MODE_LABEL[mode]}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {MARKERS.map((marker) => (
            <tr key={marker.text}>
              <td className="mono">{marker.text}</td>
              <td>{`${marker.homeLayer} · ${marker.homeGroup}`}</td>
              {MODES.map((mode) => {
                const list = hits[mode].get(marker.text) ?? []
                return (
                  <td key={mode}>
                    {list.length === 0 && <span className="muted">나온 노트 없음</span>}
                    {list.map((hit) => (
                      <div key={hit.note.note_id} className="mk-item">
                        <button
                          className="link"
                          onClick={(e) => onOpenNoteInMode(mode, hit.note.note_id, e)}
                          onAuxClick={(e) => e.button === 1 && onOpenNoteInMode(mode, hit.note.note_id, e)}
                        >
                          {hit.note.title}
                        </button>
                        <span className="muted">
                          {' '}
                          <span style={{ color: LAYER_COLOR[hit.note.layer] }}>{hit.note.layer}</span>
                          {hit.note.group_label ? ` · ${hit.note.group_label}` : ''}
                          {hit.count > 1 ? ` × ${hit.count}` : ''}
                        </span>{' '}
                        <span className={`kind kind-${hit.kind}`}>{MARKER_KIND_LABEL[hit.kind]}</span>
                      </div>
                    ))}
                  </td>
                )
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
