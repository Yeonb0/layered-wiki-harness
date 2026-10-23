// 사용자 결정 2026-10-21 · 23 : 시연 경로 전용 화면 - 본문 표시는 "## " 소제목만 따로 보이고 마크다운 라이브러리를 쓰지 않는다

export type BodyLine = { kind: 'heading' | 'text'; text: string }

// "## " 로 시작하는 줄은 ## 글자를 빼고 소제목으로, 다른 줄은 그대로 둔다 ( 줄바꿈은 줄 단위로 유지 )
export function bodyLines(body: string): BodyLine[] {
  return body.split('\n').map((line) =>
    line.startsWith('## ') ? { kind: 'heading', text: line.slice(3).trim() } : { kind: 'text', text: line },
  )
}
