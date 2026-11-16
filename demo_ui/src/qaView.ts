// 사용자 결정 2026-11-16 : Q&A 탭 - 서버 응답을 화면 모양으로 바꾸는 순수 함수. 보기 밖 노트의 제목 · 본문은 서버가 내보내지 않으므로 화면도 id 만 다룬다
import type { AskResponse, AskSource } from './api'

export type QaView = {
  answer: string
  // cited_ids 순서대로 정렬한 근거 노트 - sources 에 없는 id 는 건너뛴다 ( 보기 밖 인용은 아래 목록으로 간다 )
  sources: AskSource[]
  // 보기 밖 인용 - id 만 있다
  outOfView: string[]
  elapsedSeconds: number
}

export function toQaView(response: AskResponse): QaView {
  const byId = new Map(response.sources.map((source) => [source.note_id, source]))
  const sources: AskSource[] = []
  for (const id of response.cited_ids) {
    const source = byId.get(id)
    if (source !== undefined && !sources.includes(source)) sources.push(source)
  }
  return {
    // 답 텍스트는 고치지 않는다
    answer: response.answer,
    sources,
    outOfView: [...response.out_of_view_ids],
    elapsedSeconds: response.elapsed_seconds,
  }
}

// 상태 코드별 안내 - 그 밖의 오류는 서버 message 를 그대로 보인다
export function askErrorText(status: number | null, message: string): string {
  if (status === 503) return 'Q&A 가 설정되지 않았다 (--dify-qa-key-env)'
  if (status === 409) return '다른 작업이 도는 중'
  return message
}
