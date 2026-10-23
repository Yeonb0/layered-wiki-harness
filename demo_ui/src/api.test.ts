import { afterEach, describe, expect, it, vi } from 'vitest'
import { fetchView, fetchViewers } from './api'

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

  it('HTTP 오류는 오류로 올린다', async () => {
    vi.stubEnv('VITE_API_BASE', 'http://api.test')
    vi.stubGlobal('fetch', async () => ({ ok: false, status: 400, json: async () => ({}) }))
    await expect(fetchView('all_layers', '없는보는사람')).rejects.toThrow('400')
  })
})
