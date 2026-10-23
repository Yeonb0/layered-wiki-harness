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

export type HealthResponse = {
  status: string
  modes: Mode[]
  base_notes: Record<string, number>
  base_run: string
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

// 본문 오류 ( error_type · message ) 가 있으면 문구에 담는다 - 라이브 투입의 503 · 409 를 화면이 구분해 보이려는 것
async function postJson<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(`${apiBase()}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!response.ok) {
    let detail = ''
    try {
      const parsed = (await response.json()) as { error_type?: string; message?: string }
      detail = [parsed.error_type, parsed.message].filter(Boolean).join(' : ')
    } catch {
      detail = ''
    }
    throw new Error(`요청 실패 ( ${response.status} ) : ${path}${detail ? ` : ${detail}` : ''}`)
  }
  return (await response.json()) as T
}

export function fetchViewers(): Promise<ViewersResponse> {
  return getJson<ViewersResponse>('/viewers')
}

export function fetchView(mode: Mode, viewerId: string, jobId?: string | null): Promise<ViewResponse> {
  // viewer_id 에 한글이 들어 있어 쿼리를 문자열로 이어 붙이지 않는다 - job 이 있으면 그 작업의 새 노트를 겹친 보기를 받는다
  const query = new URLSearchParams({ mode, viewer: viewerId })
  if (jobId) query.set('job', jobId)
  return getJson<ViewResponse>(`/view?${query.toString()}`)
}

export function fetchHealth(): Promise<HealthResponse> {
  return getJson<HealthResponse>('/health')
}

// GET /docs 의 한 항목 - 제목 · 본문 · 그룹 이름은 서버가 내보내지 않는다
export type DocItem = {
  doc_id: string
  layer: string
  segments: number
  chars: number
}

export function fetchDocs(): Promise<DocItem[]> {
  return getJson<DocItem[]>('/docs')
}

// GET /live 의 레코드 ( 서버 DemoApp.live_status ) - 라이브가 없으면 { status: 'idle' }
export type LiveRecord = {
  live_id: string
  doc_id: string
  mode: Mode
  status: 'running' | 'completed' | 'failed'
  started_at_utc: string
  finished_at_utc: string | null
  elapsed_seconds: number | null
  workflow_run_id: string | null
  dify_status: string | null
  dify_outputs: unknown
  job_id: string | null
  error: { error_type: string; message: string } | null
}

export type LiveState = LiveRecord | { status: 'idle' }

export function fetchLive(): Promise<LiveState> {
  return getJson<LiveState>('/live')
}

export function postLive(docId: string, mode: Mode): Promise<{ ok: true; live_id: string }> {
  return postJson('/live', { doc_id: docId, mode })
}

// 작업 결과의 노트 한 건 ( 서버 DemoApp._notes_payload ) - 배치에 실패한 노트는 note_id · layer 가 null 이다
export type JobNote = {
  note_id: string | null
  title: string | null
  layer: string | null
  group_label: string | null
  source_segment_ids: string[]
  upward_links: string[]
  downward_links: { target_id: string; target_layer: string; target_group_label: string | null }[]
  candidates: { id: string; layer: string }[]
  problems: string[]
}

export type JobResult =
  | {
      ok: boolean
      elapsed_s: number
      request_dir: string
      decompose: { ok: boolean; error: string | null; note_count: number }
      notes: JobNote[]
      summary_text: string
    }
  | { ok: false; error_type: string; message: string }

// GET /jobs/<id> 의 응답 ( 서버 DemoApp.job_status ) - 돌고 있으면 elapsed_s, 끝났으면 http_status · result 가 온다
export type JobStatus = {
  job_id: string
  status: 'running' | 'completed' | 'failed'
  doc_id: string
  mode: Mode
  elapsed_s?: number
  http_status?: number | null
  result?: JobResult | null
}

export function fetchJob(jobId: string): Promise<JobStatus> {
  return getJson<JobStatus>(`/jobs/${jobId}?wait=0`)
}
