import { describe, expect, it } from 'vitest'
import type { AskResponse } from './api'
import { askErrorText, toQaView } from './qaView'

// 픽스처일 뿐이며 규칙과 무관하다 - 합성 값이다
function response(over: Partial<AskResponse> = {}): AskResponse {
  return {
    mode: 'all_layers', viewer_id: '전사', query: '합성 질문', answer: '합성 답 [가] [나]', cited_ids: ['가', '나'],
    sources: [
      { note_id: '나', title: '합성 나', layer: '팀', group_label: '팀가' },
      { note_id: '가', title: '합성 가', layer: '전사', group_label: null },
    ],
    out_of_view_ids: [], message_id: 'm', conversation_id: 'c', elapsed_seconds: 12.5, ...over,
  }
}

describe('toQaView', () => {
  it('답 텍스트를 그대로 두고 근거를 cited_ids 순서로 정렬한다', () => {
    const view = toQaView(response())
    expect(view.answer).toBe('합성 답 [가] [나]')
    expect(view.sources.map((s) => s.note_id)).toEqual(['가', '나'])
    expect(view.elapsedSeconds).toBe(12.5)
  })

  it('보기 밖 인용은 id 만 따로 담고 근거 목록에는 넣지 않는다', () => {
    const view = toQaView(response({ cited_ids: ['가', '밖'], out_of_view_ids: ['밖'] }))
    expect(view.sources.map((s) => s.note_id)).toEqual(['가'])
    expect(view.outOfView).toEqual(['밖'])
  })

  it('인용이 없으면 근거도 보기 밖 인용도 비어 있다', () => {
    const view = toQaView(response({ cited_ids: [], sources: [], answer: '인용 없는 답' }))
    expect(view.sources).toEqual([])
    expect(view.outOfView).toEqual([])
  })

  it('cited_ids 에 중복이 있어도 근거는 한 번만 나온다', () => {
    const view = toQaView(response({ cited_ids: ['가', '가', '나'] }))
    expect(view.sources.map((s) => s.note_id)).toEqual(['가', '나'])
  })
})

describe('askErrorText', () => {
  it('503 · 409 는 안내 문구, 그 밖은 서버 message 를 그대로 보인다', () => {
    expect(askErrorText(503, 'x')).toBe('Q&A 가 설정되지 않았다 (--dify-qa-key-env)')
    expect(askErrorText(409, 'x')).toBe('다른 작업이 도는 중')
    expect(askErrorText(502, 'Dify HTTP 500')).toBe('Dify HTTP 500')
    expect(askErrorText(null, '네트워크 오류')).toBe('네트워크 오류')
  })
})
