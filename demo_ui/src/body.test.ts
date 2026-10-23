import { describe, expect, it } from 'vitest'
import { bodyLines } from './body'

// 픽스처일 뿐이며 규칙과 무관하다 - 본문은 합성이다
describe('bodyLines', () => {
  it('"## " 로 시작하는 줄은 ## 를 빼고 소제목 줄이 된다', () => {
    expect(bodyLines('## 제목')).toEqual([{ kind: 'heading', text: '제목' }])
  })

  it('일반 줄은 그대로 두고 줄 수와 빈 줄을 유지한다', () => {
    expect(bodyLines('첫 줄\n\n  들여쓴 줄')).toEqual([
      { kind: 'text', text: '첫 줄' },
      { kind: 'text', text: '' },
      { kind: 'text', text: '  들여쓴 줄' },
    ])
  })

  it('### 나 ##글자 처럼 "## " 로 시작하지 않는 줄은 바꾸지 않는다', () => {
    expect(bodyLines('### 작은 제목\n##붙은 글자')).toEqual([
      { kind: 'text', text: '### 작은 제목' },
      { kind: 'text', text: '##붙은 글자' },
    ])
  })

  it('소제목과 일반 줄이 섞여도 순서를 유지한다', () => {
    expect(bodyLines('앞\n## 가\n뒤').map((l) => l.kind)).toEqual(['text', 'heading', 'text'])
  })
})
