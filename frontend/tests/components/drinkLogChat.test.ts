import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { nextTick, ref, type Ref } from 'vue'
import DrinkLogChat from '~/components/DrinkLogChat.vue'

const auth = vi.hoisted(() => ({ currentUserId: null as unknown, getToken: vi.fn() }))
vi.mock('~/composables/useAuth', () => ({
  useAuth: () => ({
    currentUserId: auth.currentUserId,
    getToken: auth.getToken,
    waitForAuthReady: async () => {},
  }),
}))

const response = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status })
const fetchMock = vi.fn()
const submit = async (wrapper: VueWrapper, message = '最近の一杯は？') => {
  const textarea = wrapper.get<HTMLTextAreaElement>('textarea').element
  textarea.value = message
  textarea.dispatchEvent(new Event('input', { bubbles: true }))
  await nextTick()
  wrapper.get('form').element.dispatchEvent(new Event('submit', { cancelable: true }))
  await flushPromises()
}

beforeEach(() => {
  vi.useFakeTimers()
  auth.currentUserId = ref('user-1')
  auth.getToken.mockResolvedValue('id-token')
  fetchMock.mockReset()
  vi.stubGlobal('useRuntimeConfig', () => ({ public: { apiBaseUrl: 'https://api.test.whiskeybar.site' } }))
  vi.stubGlobal('fetch', fetchMock)
})

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

describe('Drink Log chat', () => {
  it('submits an authenticated question, polls and shows the answer', async () => {
    fetchMock.mockResolvedValueOnce(response({ request_id: 'job-1', status: 'pending' }, 202))
      .mockResolvedValueOnce(response({ request_id: 'job-1', status: 'running' }))
      .mockResolvedValueOnce(response({ request_id: 'job-1', status: 'complete', answer: '最近はアランを飲んでいます。' }))
    const wrapper = mount(DrinkLogChat)
    const textarea = wrapper.get<HTMLTextAreaElement>('textarea').element
    textarea.value = '最近飲んだ銘柄は？'
    textarea.dispatchEvent(new Event('input', { bubbles: true }))
    await nextTick()
    wrapper.get('form').element.dispatchEvent(new Event('submit', { cancelable: true }))
    await flushPromises()
    await vi.advanceTimersByTimeAsync(1000)
    await vi.advanceTimersByTimeAsync(1000)
    await flushPromises()

    const [url, options] = fetchMock.mock.calls[0]
    expect(url).toBe('https://api.test.whiskeybar.site/api/chat')
    expect(options.method).toBe('POST')
    expect(options.headers.get('Authorization')).toBe('Bearer id-token')
    expect(JSON.parse(options.body)).toEqual({
      message: '最近飲んだ銘柄は？', history: [],
      session_id: expect.stringMatching(/^[\da-f-]{36}$/),
      request_id: expect.stringMatching(/^[\da-f-]{36}$/),
    })
    expect(fetchMock.mock.calls[1][0]).toBe('https://api.test.whiskeybar.site/api/chat/job-1')
    expect(wrapper.text()).toContain('最近はアランを飲んでいます。')
    expect(wrapper.find('[role="status"]').exists()).toBe(false)
    wrapper.unmount()
  })

  it.each(['reset', 'user change', 'unmount'])('aborts the pending request and discards a late answer on %s', async (action) => {
    let resolveRequest!: (value: Response) => void
    fetchMock.mockImplementationOnce(() => new Promise<Response>((resolve) => { resolveRequest = resolve }))
    const wrapper = mount(DrinkLogChat)
    await submit(wrapper)
    const signal = fetchMock.mock.calls[0][1].signal as AbortSignal
    if (action === 'reset') {
      wrapper.get<HTMLButtonElement>('button[aria-label="会話をリセット"]').element.click()
    } else if (action === 'user change') {
      (auth.currentUserId as Ref<string>).value = 'user-2'
    } else wrapper.unmount()
    await nextTick()
    expect(signal.aborted).toBe(true)
    expect(vi.getTimerCount()).toBe(0)
    resolveRequest(response({ request_id: 'old-job', status: 'complete', answer: '前のユーザーの記録' }))
    await flushPromises()
    expect(wrapper.text()).not.toContain('前のユーザーの記録')
    expect(fetchMock).toHaveBeenCalledTimes(1)
    if (action !== 'unmount') {
      expect(wrapper.text()).not.toContain('最近の一杯は？')
      fetchMock.mockResolvedValueOnce(response({ request_id: 'new-job', status: 'complete', answer: '新しい会話' }))
      await submit(wrapper)
      const first = JSON.parse(fetchMock.mock.calls[0][1].body)
      const second = JSON.parse(fetchMock.mock.calls[1][1].body)
      expect(second.history).toEqual([])
      expect(second.session_id).not.toBe(first.session_id)
      wrapper.unmount()
    }
  })

  it('rejects oversized questions and sends bounded recent conversation history', async () => {
    const wrapper = mount(DrinkLogChat)
    await submit(wrapper, '長'.repeat(2001))
    expect(fetchMock).not.toHaveBeenCalled()
    expect(wrapper.get('[role="alert"]').text()).toContain('2000')
    for (let index = 0; index < 7; index++) {
      fetchMock.mockResolvedValueOnce(response({ request_id: `job-${index}`, status: 'complete', answer: `回答${index}` + '答'.repeat(1997) }))
      await submit(wrapper, `質問${index}` + '問'.repeat(1997))
    }
    const body = JSON.parse(fetchMock.mock.calls[6][1].body)
    expect(body.history).toHaveLength(6)
    expect(body.history[0].text).toContain('質問3')
    expect(body.history.map((message: { role: string }) => message.role)).toEqual(['user', 'assistant', 'user', 'assistant', 'user', 'assistant'])
    expect(body.history.reduce((total: number, message: { text: string }) => total + message.text.length, 0)).toBe(12000)
    wrapper.unmount()
  })

  it.each([
    [429, { error: 'Chat usage budget exceeded' }, '本日のチャットの上限'],
    [503, { error: 'Chat usage budget exceeded' }, '今月のチャットの上限'],
    [200, { request_id: 'job-1', status: 'failed', error: '回答の取得に失敗しました。' }, '回答の取得に失敗しました。'],
  ])('shows request failures and allows a new question (%s)', async (status, body, message) => {
    fetchMock.mockResolvedValueOnce(response(body, status))
    const wrapper = mount(DrinkLogChat)
    await submit(wrapper)
    expect(wrapper.get('[role="alert"]').text()).toContain(message)
    fetchMock.mockResolvedValueOnce(response({ request_id: 'job-2', status: 'complete', answer: '山崎です。' }))
    await submit(wrapper, '山崎は飲んだ？')
    expect(wrapper.find('[role="alert"]').exists()).toBe(false)
    expect(wrapper.text()).toContain('山崎です。')
    expect(JSON.parse(fetchMock.mock.calls[1][1].body).history).toEqual([])
    wrapper.unmount()
  })

  it('prevents double submits and stops polling after 150 seconds', async () => {
    fetchMock.mockImplementation(async (_url, options) => response({ request_id: 'job-1', status: options.method === 'POST' ? 'pending' : 'running' }, options.method === 'POST' ? 202 : 200))
    const wrapper = mount(DrinkLogChat)
    await submit(wrapper)
    await submit(wrapper, '重複した質問')
    expect(fetchMock.mock.calls.filter(([, options]) => options.method === 'POST')).toHaveLength(1)
    await vi.advanceTimersByTimeAsync(150000)
    await flushPromises()
    expect(wrapper.get('[role="alert"]').text()).toContain('時間がかかっています')
    expect(wrapper.find('[role="status"]').exists()).toBe(false)
    const requestCount = fetchMock.mock.calls.length
    await vi.advanceTimersByTimeAsync(5000)
    expect(fetchMock).toHaveBeenCalledTimes(requestCount)
    expect((fetchMock.mock.calls[0][1].signal as AbortSignal).aborted).toBe(true)
    wrapper.unmount()
  })
})
