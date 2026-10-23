import { afterEach, describe, expect, it, vi } from 'vitest'
import { fetchDocs, fetchHealth, fetchJob, fetchLive, fetchView, fetchViewers, postLive } from './api'

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
