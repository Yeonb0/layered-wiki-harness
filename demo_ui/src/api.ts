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

// 사용자 결정 2026-10-23 ( 지침 v3.1 ) : 시연 경로 회의 기능. 회의 · 할 일은 서버가 보는 사람별로 거른 것만 그린다. 보는 사람 선택은 인증이 아니다
// 아래 타입은 서버 응답 키 그대로다 ( serve/meetings.py 의 _MEETING_KEYS · _TASK_KEYS · list_workspaces )
export type Workspace = { layer: string; group: string | null }

export type WorkspaceOption = { workspace: Workspace; label: string; members: string[] }

export type MeetingStatus = 'scheduled' | 'done' | 'cancelled'
export type TaskStatus = 'todo' | 'doing' | 'done'
export type TaskSource = 'human' | 'agent_proposal' | 'agent_confirmed'

export type Meeting = {
  meeting_id: string
  title: string
  starts_at: string
  ends_at: string
  workspace: Workspace
  attendees: string[]
  agenda: string[]
  minutes_doc_id: string | null
  status: MeetingStatus
  // 시드 회의에는 없어 null 로 온다
  created_by: string | null
  updated_at: string | null
}

export type ProgressEntry = { at: string; author: string; text: string }

export type Task = {
  task_id: string
  meeting_id: string | null
  title: string
  workspace: Workspace
  assignee: string
  due: string | null
  status: TaskStatus
  source: TaskSource
  progress: ProgressEntry[]
}

// 400 · 404 · 503 의 본문 ( error_type · message ) 을 담는다 - 화면은 message 를 그대로 보인다
export class ApiError extends Error {
  status: number
  errorType: string
  constructor(status: number, errorType: string, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.errorType = errorType
  }
}

async function meetingsRequest<T>(method: 'GET' | 'POST', path: string, body?: unknown): Promise<T> {
  const response = await fetch(`${apiBase()}${path}`, {
    method,
    headers: method === 'POST' ? { 'Content-Type': 'application/json' } : undefined,
    body: method === 'POST' ? JSON.stringify(body) : undefined,
  })
  if (!response.ok) {
    let parsed: { error_type?: string; message?: string } = {}
    try {
      parsed = (await response.json()) as { error_type?: string; message?: string }
    } catch {
      parsed = {}
    }
    throw new ApiError(response.status, parsed.error_type ?? 'Unknown', parsed.message ?? `요청 실패 ( ${response.status} ) : ${path.split('?')[0]}`)
  }
  return (await response.json()) as T
}

function withQuery(path: string, params: Record<string, string | undefined>): string {
  // 한글이 들어 있어 쿼리를 문자열로 이어 붙이지 않는다
  const query = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined) query.set(key, value)
  }
  return `${path}?${query.toString()}`
}

export async function fetchWorkspaces(viewer: string): Promise<WorkspaceOption[]> {
  return (await meetingsRequest<{ workspaces: WorkspaceOption[] }>('GET', withQuery('/workspaces', { viewer }))).workspaces
}

export async function fetchMeetings(viewer: string, from?: string, to?: string): Promise<Meeting[]> {
  return (await meetingsRequest<{ meetings: Meeting[] }>('GET', withQuery('/meetings', { viewer, from, to }))).meetings
}

export function fetchMeeting(viewer: string, meetingId: string): Promise<Meeting> {
  return meetingsRequest<Meeting>('GET', withQuery(`/meetings/${meetingId}`, { viewer }))
}

// 만들기 · 고치기 본문 ( 서버 _MEETING_INPUT ) - 고칠 때는 바꿀 키만 보낸다
export type MeetingInput = {
  title: string
  starts_at: string
  ends_at: string
  workspace: Workspace
  attendees: string[]
  agenda: string[]
  minutes_doc_id: string | null
  status: MeetingStatus
}

export function createMeeting(viewer: string, fields: Partial<MeetingInput>): Promise<Meeting> {
  return meetingsRequest<Meeting>('POST', '/meetings', { viewer, ...fields })
}

export function updateMeeting(viewer: string, meetingId: string, fields: Partial<MeetingInput>): Promise<Meeting> {
  return meetingsRequest<Meeting>('POST', `/meetings/${meetingId}`, { viewer, ...fields })
}

export async function fetchTasks(viewer: string, meeting?: string, assignee?: string): Promise<Task[]> {
  return (await meetingsRequest<{ tasks: Task[] }>('GET', withQuery('/tasks', { viewer, meeting, assignee }))).tasks
}

// 만들기 본문 ( 서버 _TASK_INPUT ) - 고칠 때는 title · assignee · due · status 만 보낸다
export type TaskInput = {
  title: string
  meeting_id: string | null
  workspace: Workspace
  assignee: string
  due: string | null
  status: TaskStatus
}

export function createTask(viewer: string, fields: Partial<TaskInput>): Promise<Task> {
  return meetingsRequest<Task>('POST', '/tasks', { viewer, ...fields })
}

export function updateTask(
  viewer: string,
  taskId: string,
  fields: Partial<Pick<TaskInput, 'title' | 'assignee' | 'due' | 'status'>>,
): Promise<Task> {
  return meetingsRequest<Task>('POST', `/tasks/${taskId}`, { viewer, ...fields })
}

export function addProgress(viewer: string, taskId: string, text: string): Promise<Task> {
  return meetingsRequest<Task>('POST', `/tasks/${taskId}/progress`, { viewer, text })
}

// 사용자 결정 2026-10-23 ( 지침 v3.1 ) : 회의록 투입 ( 차수 901 ) → 에이전트 분해 · 배치 → 참석자가 노트별 승인 / 반려 → 승인된 노트만 볼트에 겹친다
// 아래 타입의 키는 serve/demo_api.py 의 응답 코드 ( _proposal_list · _proposal_detail · _trace · _decide ) 그대로다
export type ProposalStatus = 'running' | 'awaiting_approval' | 'decided' | 'failed'

export type ProposalSummary = {
  doc_id: string
  meeting_id: string
  mode: Mode
  status: ProposalStatus
  note_count: number
  approved: number
  rejected: number
  pending: number
}

export type NoteDecision = { decision: 'approve' | 'reject'; by: string; at: string }

// 배치에 실패한 노트는 layer · group_label · body 가 null 이다 ( 서버 응답에 note_id 는 없다 )
export type ProposalNote = {
  note_index: number
  title: string | null
  layer: string | null
  group_label: string | null
  body: string | null
  source_segment_ids: string[]
  upward_links: string[]
  downward_links: { target_id: string; target_layer: string }[]
  hidden_links: number
  problems: string[]
  decision: NoteDecision | null
}

export type Proposal = ProposalSummary & { error: string | null; notes: ProposalNote[] }

export type TraceCandidate = { id: string; layer: string; group_label: string | null; title: string }

export type TracePlace = {
  note_index: number
  layer: string | null
  upward_links: string[]
  downward_links: string[]
  hidden_links: number
  problems: string[]
  candidates: TraceCandidate[]
  hidden_candidates: number
  rationale: string | null
  rationale_hidden: boolean
}

export type Trace = {
  doc_id: string
  meeting_id: string
  mode: Mode
  decompose: { ok: boolean; error: string | null; notes: { note_index: number; title: string; segment_ids: string[] }[] }
  places: TracePlace[]
}

export function submitMinutes(viewer: string, meetingId: string, mode: Mode, text: string): Promise<{ ok: true; doc_id: string; job_id: string }> {
  return meetingsRequest('POST', '/minutes', { viewer, meeting_id: meetingId, mode, text })
}

export async function fetchProposals(viewer: string): Promise<ProposalSummary[]> {
  return (await meetingsRequest<{ proposals: ProposalSummary[] }>('GET', withQuery('/proposals', { viewer }))).proposals
}

export function fetchProposal(viewer: string, docId: string): Promise<Proposal> {
  return meetingsRequest<Proposal>('GET', withQuery(`/proposals/${docId}`, { viewer }))
}

export function fetchTrace(viewer: string, docId: string): Promise<Trace> {
  return meetingsRequest<Trace>('GET', withQuery(`/proposals/${docId}/trace`, { viewer }))
}

export function decideProposal(
  viewer: string,
  docId: string,
  decisions: { note_index: number; decision: 'approve' | 'reject' }[],
): Promise<{ ok: true; doc_id: string; status: ProposalStatus; approved: number; rejected: number; pending: number }> {
  return meetingsRequest('POST', `/proposals/${docId}/decide`, { viewer, decisions })
}
