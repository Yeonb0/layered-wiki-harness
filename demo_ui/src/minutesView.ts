// 사용자 결정 2026-10-23 ( 지침 v3.1 ) : 회의록 투입 ( 차수 901 ) → 에이전트 분해 · 배치 → 참석자가 노트별 승인 / 반려 → 승인된 노트만 볼트에 겹친다. 승인 게이트는 승격이 아니다
// 서버가 준 제안을 화면 모양으로 세는 순수 함수 - 거르거나 고치지 않는다
import type { ProposalNote, ProposalStatus } from './api'

export function proposalCounts(proposal: { notes: ProposalNote[] }): { approved: number; rejected: number; pending: number } {
  const counts = { approved: 0, rejected: 0, pending: 0 }
  for (const note of proposal.notes) {
    if (note.decision === null) counts.pending += 1
    else if (note.decision.decision === 'approve') counts.approved += 1
    else counts.rejected += 1
  }
  return counts
}

// 배치에 실패한 노트는 층이 null 이고 승인할 수 없다 ( 반려만 ) - 이미 결정한 노트도 다시 결정하지 않는다
export function canApprove(note: Pick<ProposalNote, 'layer' | 'decision'>): boolean {
  return note.layer !== null && note.decision === null
}

const STATUS_LABEL: Record<ProposalStatus, string> = {
  running: '처리 중',
  awaiting_approval: '승인 대기',
  decided: '결정 완료',
  failed: '실패',
}

export function statusLabel(status: string): string {
  if (!(status in STATUS_LABEL)) throw new Error(`알 수 없는 제안 상태 : ${status}`)
  return STATUS_LABEL[status as ProposalStatus]
}
