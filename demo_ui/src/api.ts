// 사용자 결정 2026-10-21 · 23 : 시연 경로 전용 화면 - 보는 사람별 거르기는 서버가 하고 화면은 받은 것만 그린다
// 응답 데이터는 거르거나 고치지 않는다

export type Mode = 'all_layers' | 'split_by_layer'

export type Viewer = {
  viewer_id: string
  layer: string
  label: string
  teams: string[]
}

export type ViewersResponse = {
  show_names: boolean
  viewers: Viewer[]
}

export type ViewNote = {
  note_id: string
  title: string
  layer: string
  group_label: string | null
  body: string
  source_doc_id: string
  source_layer: string
  source_segment_ids: string[]
  upward_links: string[]
  opened_downward_links: string[]
  inserted_at_vault_size: number
}

export type ViewCounts = {
  conditional_links_opened: number
  conditional_links_hidden: number
  upward_links_hidden: number
}

export type ViewResponse = {
  mode: Mode
  viewer_id: string
  show_names: boolean
  notes: ViewNote[]
  counts: ViewCounts
}

// 코드에 API 주소 기본값을 두지 않는다 - 값이 없으면 호출 때 오류를 낸다
export function apiBase(): string {
  const base = import.meta.env.VITE_API_BASE
  if (!base) {
    throw new Error('VITE_API_BASE 가 설정되지 않았다 ( .env.development 를 확인한다 )')
  }
  return base.replace(/\/+$/, '')
}

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(`${apiBase()}${path}`)
  if (!response.ok) {
    throw new Error(`요청 실패 ( ${response.status} ) : ${path.split('?')[0]}`)
  }
  return (await response.json()) as T
}

export function fetchViewers(): Promise<ViewersResponse> {
  return getJson<ViewersResponse>('/viewers')
}

export function fetchView(mode: Mode, viewerId: string): Promise<ViewResponse> {
  // viewer_id 에 한글이 들어 있어 쿼리를 문자열로 이어 붙이지 않는다
  const query = new URLSearchParams({ mode, viewer: viewerId })
  return getJson<ViewResponse>(`/view?${query.toString()}`)
}
