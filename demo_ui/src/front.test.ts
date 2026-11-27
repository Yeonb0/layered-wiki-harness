import { describe, expect, it } from 'vitest'
import { liveLabels, modelNotice } from './front'

describe('liveLabels', () => {
  it('dify 이거나 모르면 Dify 문구', () => {
    expect(liveLabels('dify')).toEqual({ button: 'Dify 로 투입', step1: '① Dify 실행 시작' })
    expect(liveLabels(undefined)).toEqual({ button: 'Dify 로 투입', step1: '① Dify 실행 시작' })
  })

  it('direct 면 Dify 를 말하지 않는다', () => {
    expect(liveLabels('direct')).toEqual({ button: '투입', step1: '① 작업 접수' })
  })
})

describe('modelNotice', () => {
  it('두 모델이 다르면 둘 다 적는다', () => {
    expect(modelNotice({ model_id: 'qwen/qwen3.5-9b', base_model_id: 'Qwen3-8B-Q4_K_M' })).toBe(
      '미리 돌린 볼트 : 로컬 Qwen3-8B-Q4_K_M · 라이브 모델 : qwen/qwen3.5-9b',
    )
  })

  it('같으면 한 번만', () => {
    expect(modelNotice({ model_id: 'Qwen3-8B-Q4_K_M', base_model_id: 'Qwen3-8B-Q4_K_M' })).toBe('라이브 모델 : Qwen3-8B-Q4_K_M')
  })

  it('model_id 가 없으면 (옛 서버) 적지 않는다', () => {
    expect(modelNotice({})).toBeNull()
    expect(modelNotice(null)).toBeNull()
  })
})
