import { describe, expect, it } from 'vitest'
import { back, backValid, canBack, canForward, EMPTY_HISTORY, forward, forwardValid, HISTORY_MAX, push, type History } from './history'

const build = (...keys: string[]): History => keys.reduce(push, EMPTY_HISTORY)

describe('history', () => {
  it('같은 키가 이어지면 쌓지 않는다', () => {
    expect(build('a', 'a', 'b', 'b')).toEqual({ stack: ['a', 'b'], index: 1 })
  })

  it('처음에는 뒤로도 앞으로도 갈 수 없다', () => {
    expect(canBack(EMPTY_HISTORY)).toBe(false)
    expect(canForward(EMPTY_HISTORY)).toBe(false)
    expect(canBack(build('a'))).toBe(false)
  })

  it('뒤로 · 앞으로는 끝에서 그대로다', () => {
    const history = build('a', 'b')
    expect(back(history)).toEqual({ stack: ['a', 'b'], index: 0 })
    expect(back(back(history))).toEqual({ stack: ['a', 'b'], index: 0 })
    expect(forward(history)).toBe(history)
    expect(forward(back(history))).toEqual(history)
  })

  it('뒤로 간 뒤에 쌓으면 앞쪽을 버린다', () => {
    const history = push(back(back(build('a', 'b', 'c'))), 'd')
    expect(history).toEqual({ stack: ['a', 'd'], index: 1 })
    expect(canForward(history)).toBe(false)
  })

  it('상한을 넘으면 오래된 것부터 버린다', () => {
    let history = EMPTY_HISTORY
    for (let n = 0; n < HISTORY_MAX + 5; n += 1) history = push(history, `k${n}`)
    expect(history.stack).toHaveLength(HISTORY_MAX)
    expect(history.stack[0]).toBe('k5')
    expect(history.index).toBe(HISTORY_MAX - 1)
  })

  it('backValid · forwardValid 는 쓸 수 없는 항목을 건너뛴다', () => {
    const history = build('a', 'x', 'y', 'b')
    const valid = (key: string) => key !== 'x' && key !== 'y'
    const moved = backValid(history, valid)
    expect(moved.index).toBe(0)
    expect(forwardValid(moved, valid).index).toBe(3)
  })

  it('유효한 곳이 없으면 그대로다', () => {
    const history = build('a', 'x', 'b')
    expect(backValid(history, (key) => key === 'b')).toBe(history)
    expect(forwardValid(back(history), (key) => key === 'a')).toEqual(back(history))
  })
})
