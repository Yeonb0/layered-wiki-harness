import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  addProgress, ApiError, createMeeting, createTask, fetchDocs, fetchHealth, fetchJob, fetchLive, fetchMeetings, fetchTasks, fetchView,
  decideProposal, fetchProposal, fetchProposals, fetchTrace, fetchViewers, fetchWorkspaces, postLive, submitMinutes, updateMeeting, updateTask,
} from './api'

// 픽스처일 뿐이며 규칙과 무관하다 - fetch 를 가짜로 바꿔 URL 만 확인한다
function fakeFetch(body: unknown = {}) {
  const calls: string[] = []
  vi.stubGlobal('fetch', async (url: string) => {
    calls.push(url)
    return { ok: true, status: 200, json: async () => body }
  })
  return calls
}

afterEach(() => {
  vi.unstubAllEnvs()
  vi.unstubAllGlobals()
})

describe('api', () => {
  it('fetchView 는 mode 와 viewer 를 URLSearchParams 로 붙인다', async () => {
    vi.stubEnv('VITE_API_BASE', 'http://api.test')
    const calls = fakeFetch()
    await fetchView('split_by_layer', '개인:샘플가')
    const url = new URL(calls[0])
    expect(url.origin + url.pathname).toBe('http://api.test/view')
    expect(url.searchParams.get('mode')).toBe('split_by_layer')
    expect(url.searchParams.get('viewer')).toBe('개인:샘플가')
    // 한글과 콜론을 문자열로 이어 붙이지 않고 퍼센트 인코딩한다
    expect(calls[0]).not.toContain('개인')
    expect(calls[0]).toContain('%')
  })

  it('끝의 슬래시가 있어도 경로가 겹치지 않는다', async () => {
    vi.stubEnv('VITE_API_BASE', 'http://api.test/')
    const calls = fakeFetch()
    await fetchViewers()
    expect(calls[0]).toBe('http://api.test/viewers')
  })

  it('VITE_API_BASE 가 없으면 오류다', async () => {
    vi.stubEnv('VITE_API_BASE', '')
    const calls = fakeFetch()
    await expect(fetchViewers()).rejects.toThrow('VITE_API_BASE')
    await expect(fetchView('all_layers', '전사')).rejects.toThrow('VITE_API_BASE')
    expect(calls).toEqual([])
  })

  it('응답 데이터를 고치지 않고 그대로 돌려준다', async () => {
    vi.stubEnv('VITE_API_BASE', 'http://api.test')
    const body = { show_names: true, viewers: [{ viewer_id: '전사', layer: '전사', label: '전사', teams: [] }] }
    fakeFetch(body)
    expect(await fetchViewers()).toEqual(body)
  })

  it('fetchHealth 는 /health 를 부르고 응답을 그대로 돌려준다', async () => {
    vi.stubEnv('VITE_API_BASE', 'http://api.test')
    const body = { status: 'ok', modes: ['all_layers'], base_notes: { all_layers: 3 }, base_run: '합성 실행' }
    const calls = fakeFetch(body)
    expect(await fetchHealth()).toEqual(body)
    expect(calls).toEqual(['http://api.test/health'])
  })

  it('fetchView 는 job 이 있을 때만 job 쿼리를 붙인다', async () => {
    vi.stubEnv('VITE_API_BASE', 'http://api.test')
    const calls = fakeFetch()
    await fetchView('all_layers', '전사')
    await fetchView('all_layers', '전사', null)
    await fetchView('split_by_layer', '개인:샘플가', 'a'.repeat(32))
    expect(new URL(calls[0]).searchParams.has('job')).toBe(false)
    expect(new URL(calls[1]).searchParams.has('job')).toBe(false)
    const url = new URL(calls[2])
    expect(url.searchParams.get('job')).toBe('a'.repeat(32))
    expect(url.searchParams.get('mode')).toBe('split_by_layer')
    expect(url.searchParams.get('viewer')).toBe('개인:샘플가')
  })

  it('fetchDocs · fetchLive · fetchJob 은 각자의 경로를 부른다', async () => {
    vi.stubEnv('VITE_API_BASE', 'http://api.test')
    const calls = fakeFetch([])
    await fetchDocs()
    await fetchLive()
    await fetchJob('b'.repeat(32))
    expect(calls).toEqual(['http://api.test/docs', 'http://api.test/live', `http://api.test/jobs/${'b'.repeat(32)}?wait=0`])
  })

  it('postLive 는 POST /live 에 doc_id · mode 를 JSON 으로 보낸다', async () => {
    vi.stubEnv('VITE_API_BASE', 'http://api.test')
    const seen: { url: string; init: RequestInit }[] = []
    vi.stubGlobal('fetch', async (url: string, init: RequestInit) => {
      seen.push({ url, init })
      return { ok: true, status: 202, json: async () => ({ ok: true, live_id: 'x' }) }
    })
    expect(await postLive('문서', 'all_layers')).toEqual({ ok: true, live_id: 'x' })
    expect(seen[0].url).toBe('http://api.test/live')
    expect(seen[0].init.method).toBe('POST')
    expect(JSON.parse(String(seen[0].init.body))).toEqual({ doc_id: '문서', mode: 'all_layers' })
  })

  it('postLive 의 HTTP 오류는 상태 코드와 error_type 을 문구에 담는다', async () => {
    vi.stubEnv('VITE_API_BASE', 'http://api.test')
    vi.stubGlobal('fetch', async () => ({
      ok: false,
      status: 503,
      json: async () => ({ ok: false, error_type: 'DifyNotConfigured', message: 'Dify 가 설정되지 않았다' }),
    }))
    await expect(postLive('문서', 'all_layers')).rejects.toThrow(/503.*DifyNotConfigured/)
  })

  it('HTTP 오류는 오류로 올린다', async () => {
    vi.stubEnv('VITE_API_BASE', 'http://api.test')
    vi.stubGlobal('fetch', async () => ({ ok: false, status: 400, json: async () => ({}) }))
    await expect(fetchView('all_layers', '없는보는사람')).rejects.toThrow('400')
  })
})

// 사용자 결정 2026-10-23 ( 지침 v3.1 ) : 시연 경로 회의 기능 - 쿼리 · 본문 만들기와 오류 본문 확인
function fakeRequests(status = 200, body: unknown = {}) {
  const calls: { url: string; init?: RequestInit }[] = []
  vi.stubGlobal('fetch', async (url: string, init?: RequestInit) => {
    calls.push({ url, init })
    return { ok: status < 400, status, json: async () => body }
  })
  return calls
}

describe('회의 api', () => {
  it('fetchWorkspaces · fetchMeetings · fetchTasks 는 쿼리를 URLSearchParams 로 만들고 없는 값은 붙이지 않는다', async () => {
    vi.stubEnv('VITE_API_BASE', 'http://api.test')
    const calls = fakeRequests(200, { workspaces: [], meetings: [], tasks: [] })
    await fetchWorkspaces('개인:샘플가')
    await fetchMeetings('팀:샘플나', '2026-10-01', '2026-10-31')
    await fetchMeetings('전사')
    await fetchTasks('개인:샘플가', 'm0001', '샘플가')
    const urls = calls.map((call) => new URL(call.url))
    expect(urls[0].pathname).toBe('/workspaces')
    expect(urls[0].searchParams.get('viewer')).toBe('개인:샘플가')
    expect(urls[1].searchParams.get('from')).toBe('2026-10-01')
    expect(urls[1].searchParams.get('to')).toBe('2026-10-31')
    expect(urls[2].searchParams.has('from')).toBe(false)
    expect(urls[3].searchParams.get('meeting')).toBe('m0001')
    expect(urls[3].searchParams.get('assignee')).toBe('샘플가')
    expect(calls[0].url).not.toContain('샘플')
  })

  it('만들기 · 고치기 · 진행 기록은 viewer 를 본문에 넣어 POST 한다', async () => {
    vi.stubEnv('VITE_API_BASE', 'http://api.test')
    const calls = fakeRequests()
    await createMeeting('전사', { title: '합성 회의' })
    await updateMeeting('전사', 'm0001', { status: 'done' })
    await createTask('개인:샘플가', { title: '합성 할 일', assignee: '샘플가', meeting_id: 'm0001' })
    await updateTask('개인:샘플가', 't0001', { status: 'doing' })
    await addProgress('개인:샘플가', 't0001', '합성 기록')
    expect(calls.map((call) => [call.init?.method, new URL(call.url).pathname])).toEqual([
      ['POST', '/meetings'],
      ['POST', '/meetings/m0001'],
      ['POST', '/tasks'],
      ['POST', '/tasks/t0001'],
      ['POST', '/tasks/t0001/progress'],
    ])
    expect(JSON.parse(calls[0].init?.body as string)).toEqual({ viewer: '전사', title: '합성 회의' })
    expect(JSON.parse(calls[4].init?.body as string)).toEqual({ viewer: '개인:샘플가', text: '합성 기록' })
  })

  it.each([400, 404, 503])('%i 이면 본문의 error_type · message 를 담은 오류를 던진다', async (status) => {
    vi.stubEnv('VITE_API_BASE', 'http://api.test')
    fakeRequests(status, { ok: false, error_type: '합성유형', message: '합성 메시지' })
    const error = await fetchMeetings('전사').catch((e: unknown) => e)
    expect(error).toBeInstanceOf(ApiError)
    expect((error as ApiError).message).toBe('합성 메시지')
    expect((error as ApiError).errorType).toBe('합성유형')
    expect((error as ApiError).status).toBe(status)
  })
})

describe('회의록 api', () => {
  it('조회는 viewer 쿼리를 URLSearchParams 로 만든다', async () => {
    vi.stubEnv('VITE_API_BASE', 'http://api.test')
    const calls = fakeRequests(200, { proposals: [] })
    await fetchProposals('개인:샘플가')
    await fetchProposal('개인:샘플가', '90100000000000000000000000000001')
    await fetchTrace('개인:샘플가', '90100000000000000000000000000001')
    const urls = calls.map((call) => new URL(call.url))
    expect(urls.map((url) => url.pathname)).toEqual([
      '/proposals',
      '/proposals/90100000000000000000000000000001',
      '/proposals/90100000000000000000000000000001/trace',
    ])
    expect(urls.every((url) => url.searchParams.get('viewer') === '개인:샘플가')).toBe(true)
    expect(calls[0].url).not.toContain('샘플')
  })

  it('투입과 결정은 viewer 를 본문에 넣어 POST 한다', async () => {
    vi.stubEnv('VITE_API_BASE', 'http://api.test')
    const calls = fakeRequests()
    await submitMinutes('개인:샘플가', 'm0007', 'all_layers', '합성 회의록')
    await decideProposal('개인:샘플가', '90100000000000000000000000000001', [{ note_index: 0, decision: 'approve' }])
    expect(calls.map((call) => [call.init?.method, new URL(call.url).pathname])).toEqual([
      ['POST', '/minutes'],
      ['POST', '/proposals/90100000000000000000000000000001/decide'],
    ])
    expect(JSON.parse(calls[0].init?.body as string)).toEqual({ viewer: '개인:샘플가', meeting_id: 'm0007', mode: 'all_layers', text: '합성 회의록' })
    expect(JSON.parse(calls[1].init?.body as string)).toEqual({ viewer: '개인:샘플가', decisions: [{ note_index: 0, decision: 'approve' }] })
  })

  it('409 이면 서버 message 를 담은 오류를 던진다', async () => {
    vi.stubEnv('VITE_API_BASE', 'http://api.test')
    fakeRequests(409, { ok: false, error_type: 'MinutesAlreadyLinked', message: '합성 충돌 메시지' })
    const error = await submitMinutes('전사', 'm0001', 'all_layers', '합성').catch((e: unknown) => e)
    expect(error).toBeInstanceOf(ApiError)
    expect((error as ApiError).message).toBe('합성 충돌 메시지')
    expect((error as ApiError).errorType).toBe('MinutesAlreadyLinked')
  })
})
