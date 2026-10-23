import { describe, expect, it } from 'vitest'
import readme from '../../demo_corpus/README.md?raw'
import type { ViewNote } from './api'
import { classifyMarker, findMarkers, MARKERS, splitByMarkers } from './markers'

// 픽스처일 뿐이며 규칙과 무관하다 - 이름은 전부 합성이다
function note(layer: string, group: string | null, body: string, title = '합성 제목'): ViewNote {
  return {
    note_id: `${layer}-${group}`, title, layer, group_label: group, body, source_doc_id: '문서', source_layer: layer,
    source_segment_ids: [], upward_links: [], opened_downward_links: [], inserted_at_vault_size: 0,
  }
}

// README 의 "층 · 팀별 고유 표현" 표를 읽어 [표현, 층, 그룹] 목록으로 만든다
function readmeMarkers(): string[] {
  const lines = readme.split('\n')
  const start = lines.findIndex((line) => line.includes('층 · 팀별 고유 표현'))
  const rows = lines.slice(start + 1).filter((line) => line.startsWith('|'))
  const out: string[] = []
  for (const row of rows.slice(2)) {
    const cells = row.split('|').slice(1, -1).map((cell) => cell.trim())
    const quoted = [...cells[0].matchAll(/'([^']+)'/g)].map((m) => m[1])
    // 첫 칸에 따옴표가 있으면 따옴표 안 표현, 없으면 첫 칸 전체 ( 쉼표로 나뉘면 각각 )
    let texts = quoted.length > 0 ? quoted : cells[0].split(',').map((t) => t.trim())
    // 표의 "할인율 17%" 행은 본문에 나오는 표현이 17% 라서 17% 로 대응시킨다
    texts = texts.map((t) => (t === '할인율 17%' ? '17%' : t))
    const team = cells[1].match(/^팀(\d+) 회의록/)
    const owner = cells[1].match(/^(팀원\w) 개인/)
    const home = team ? `팀|팀${team[1]}` : owner ? `개인|${owner[1]}` : null
    if (!home) throw new Error(`README 표의 둘째 칸을 해석하지 못했다 : ${cells[1]}`)
    for (const text of texts) out.push(`${text}|${home}`)
  }
  return out
}

describe('MARKERS', () => {
  it('README 의 층 · 팀별 고유 표현 표와 집합이 같다', () => {
    const fromReadme = readmeMarkers()
    expect(fromReadme.length).toBeGreaterThan(0)
    const fromCode = MARKERS.map((m) => `${m.text}|${m.homeLayer}|${m.homeGroup}`)
    expect(new Set(fromCode)).toEqual(new Set(fromReadme))
    expect(fromCode).toHaveLength(new Set(fromCode).size)
  })

  it('MARKERS 순서가 정해진 순서다', () => {
    expect(MARKERS.map((m) => m.text)).toEqual(['붉은 매듭', '황금비늘', '17%', 'sandbox-7', '133ms', '0.8%p', '1 : 0.37', '2.6점'])
  })
})

describe('classifyMarker', () => {
  const team1Marker = MARKERS[0]
  it('노트 층이 표지 층보다 위면 up', () => {
    expect(classifyMarker({ layer: '전사', group_label: null }, team1Marker)).toBe('up')
    expect(classifyMarker({ layer: '팀', group_label: '팀1' }, MARKERS[3])).toBe('up')
  })

  it('같은 층에서 그룹이 다르면 cross', () => {
    expect(classifyMarker({ layer: '팀', group_label: '팀2' }, team1Marker)).toBe('cross')
    expect(classifyMarker({ layer: '개인', group_label: '팀원B' }, MARKERS[3])).toBe('cross')
  })

  it('같은 층 같은 그룹이면 home', () => {
    expect(classifyMarker({ layer: '팀', group_label: '팀1' }, team1Marker)).toBe('home')
  })

  it('노트 층이 표지 층보다 아래면 down', () => {
    expect(classifyMarker({ layer: '개인', group_label: '팀원E' }, team1Marker)).toBe('down')
  })

  it('층 순서에 없는 층은 오류다', () => {
    expect(() => classifyMarker({ layer: '없는층', group_label: null }, team1Marker)).toThrow()
  })
})

describe('findMarkers', () => {
  it('황금비늘이 두 번 든 팀1 노트는 cross 이고 count 는 2 이다', () => {
    const found = findMarkers(note('팀', '팀1', '황금비늘 환율표와 황금비늘 기준'))
    expect(found).toHaveLength(1)
    expect(found[0]).toMatchObject({ kind: 'cross', count: 2 })
    expect(found[0].marker.text).toBe('황금비늘')
  })

  it('같은 표현이 팀2 노트에 있으면 home 이다', () => {
    expect(findMarkers(note('팀', '팀2', '황금비늘 환율표'))[0].kind).toBe('home')
  })

  it('전사 노트의 sandbox-7 은 up 이다', () => {
    expect(findMarkers(note('전사', null, 'sandbox-7 실험'))[0].kind).toBe('up')
  })

  it('개인 팀원E 노트의 붉은 매듭은 down 이다', () => {
    expect(findMarkers(note('개인', '팀원E', '붉은 매듭 테스트'))[0].kind).toBe('down')
  })

  it('공백이 다른 1:0.37 은 찾지 않는다', () => {
    expect(findMarkers(note('팀', '팀1', '비율 1:0.37 과 1  :  0.37'))).toEqual([])
    expect(findMarkers(note('팀', '팀1', '비율 1 : 0.37'))).toHaveLength(1)
  })

  it('제목에 든 표지도 센다 / 표지가 없으면 빈 목록이다', () => {
    expect(findMarkers(note('팀', '팀1', '본문', '붉은 매듭 제목'))[0].count).toBe(1)
    expect(findMarkers(note('팀', '팀1', '표지 없는 본문'))).toEqual([])
  })

  it('한 노트에 표지가 여럿이면 MARKERS 순서로 모두 돌려준다', () => {
    const found = findMarkers(note('전사', null, '2.6점 그리고 붉은 매듭'))
    expect(found.map((f) => f.marker.text)).toEqual(['붉은 매듭', '2.6점'])
  })

  it('대소문자를 무시하지 않는다', () => {
    expect(findMarkers(note('전사', null, 'SANDBOX-7'))).toEqual([])
  })
})

describe('splitByMarkers', () => {
  it('조각을 이어 붙이면 원문과 같다', () => {
    for (const text of ['', '표지 없음', '붉은 매듭과 17% 와 sandbox-7', '앞 황금비늘 뒤 황금비늘', '1 : 0.37']) {
      expect(splitByMarkers(text).map((p) => p.text).join('')).toBe(text)
    }
  })

  it('표지 조각에는 marker 가 붙고 나머지는 null 이다', () => {
    const pieces = splitByMarkers('가 붉은 매듭 나')
    expect(pieces.map((p) => p.marker?.text ?? null)).toEqual([null, '붉은 매듭', null])
  })

  it('겹치는 표지는 목록 순서상 앞의 것이 이긴다', () => {
    // 실제 표지끼리는 겹치지 않아서 겹침 규칙은 임시 목록으로 확인한다
    const first = { text: 'abcd', homeLayer: '팀', homeGroup: 'x' } as const
    const second = { text: 'cdef', homeLayer: '팀', homeGroup: 'y' } as const
    const pieces = splitByMarkers('abcdef', [first, second])
    expect(pieces.map((p) => [p.text, p.marker?.text ?? null])).toEqual([['abcd', 'abcd'], ['ef', null]])
    const reversed = splitByMarkers('abcdef', [second, first])
    expect(reversed.map((p) => [p.text, p.marker?.text ?? null])).toEqual([['ab', null], ['cdef', 'cdef']])
  })

  it('실제 표지가 이웃해도 각각 조각이 된다', () => {
    expect(splitByMarkers('17%0.8%p').map((p) => p.marker?.text)).toEqual(['17%', '0.8%p'])
  })
})
