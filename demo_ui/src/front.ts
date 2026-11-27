// 공개 시연 서버 (설계 9.7) : 앞단이 Dify 가 아니면 화면이 Dify 를 말하지 않게 문구를 고른다
import type { HealthResponse } from './api'

export type Front = 'dify' | 'direct'

export function liveLabels(front: Front | undefined): { button: string; step1: string } {
  if (front === 'direct') return { button: '투입', step1: '① 작업 접수' }
  // 옛 서버 (front 없음) 는 Dify 앞단이다
  return { button: 'Dify 로 투입', step1: '① Dify 실행 시작' }
}

// AI 사용 고지 (가이드 26쪽) : 미리 돌린 볼트를 만든 모델과 라이브 모델이 다르면 둘 다 적는다
export function modelNotice(health: Pick<HealthResponse, 'model_id' | 'base_model_id'> | null): string | null {
  if (!health || !health.model_id) return null
  if (health.base_model_id && health.base_model_id !== health.model_id) {
    return `미리 돌린 볼트 : 로컬 ${health.base_model_id} · 라이브 모델 : ${health.model_id}`
  }
  return `라이브 모델 : ${health.model_id}`
}
