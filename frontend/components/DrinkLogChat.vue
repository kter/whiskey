<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue'
import { ApiError, formatDailyQuotaReset, useApi } from '~/composables/useApi'
import { useAuth } from '~/composables/useAuth'

interface ChatMessage { role: 'user' | 'assistant'; text: string }
interface ChatJob { request_id: string; status: 'pending' | 'running' | 'complete' | 'failed'; answer?: string; error?: string }

const { request } = useApi()
const { currentUserId } = useAuth()
const input = ref('')
const messages = ref<ChatMessage[]>([])
const history = ref<ChatMessage[]>([])
const busy = ref(false)
const error = ref('')
let sessionId = crypto.randomUUID()
let generation = 0
let activeRequest: AbortController | null = null
let activeDeadline: ReturnType<typeof setTimeout> | null = null

const reset = () => {
  generation++
  activeRequest?.abort()
  activeRequest = null
  if (activeDeadline !== null) clearTimeout(activeDeadline)
  activeDeadline = null
  messages.value = []
  history.value = []
  input.value = ''
  busy.value = false
  error.value = ''
  sessionId = crypto.randomUUID()
}

watch(currentUserId, reset, { flush: 'sync' })
onBeforeUnmount(reset)

const send = async () => {
  const message = input.value.trim()
  if (busy.value || !message) return
  if (Array.from(message).length > 2000) {
    error.value = '質問は2000文字以内で入力してください。'
    return
  }
  busy.value = true
  const currentGeneration = generation
  const controller = new AbortController()
  activeRequest = controller
  const deadline = setTimeout(() => {
    if (currentGeneration !== generation) return
    generation++
    controller.abort()
    activeRequest = null
    activeDeadline = null
    busy.value = false
    error.value = '回答に時間がかかっています。しばらく待ってからもう一度お試しください。'
  }, 150000)
  activeDeadline = deadline
  error.value = ''
  const requestHistory = history.value.slice()
  messages.value.push({ role: 'user', text: message })
  input.value = ''
  try {
    let job = await request<ChatJob>('/api/chat', {
      method: 'POST', auth: 'required', signal: controller.signal,
      body: { message, history: requestHistory, session_id: sessionId, request_id: crypto.randomUUID() },
    })
    if (currentGeneration !== generation) return
    while (job.status === 'pending' || job.status === 'running') {
      await new Promise<void>((resolve) => {
        const finish = () => {
          clearTimeout(timer)
          controller.signal.removeEventListener('abort', finish)
          resolve()
        }
        const timer = setTimeout(finish, 1000)
        controller.signal.addEventListener('abort', finish, { once: true })
      })
      if (currentGeneration !== generation) return
      job = await request<ChatJob>(`/api/chat/${encodeURIComponent(job.request_id)}`, { auth: 'required', signal: controller.signal })
      if (currentGeneration !== generation) return
    }
    if (job.status === 'failed') throw new Error(job.error || '回答を取得できませんでした。')
    const answer = job.answer || ''
    messages.value.push({ role: 'assistant', text: answer })
    history.value.push({ role: 'user', text: message }, { role: 'assistant', text: Array.from(answer).slice(0, 2000).join('') })
    while (history.value.length > 10 || history.value.reduce((total, item) => total + Array.from(item.text).length, 0) > 12000) {
      history.value.splice(0, 2)
    }
  } catch (cause) {
    if (currentGeneration === generation) {
      const details = cause instanceof ApiError ? cause.details : null
      const quota = details && typeof details === 'object' && 'error' in details && details.error === 'Chat usage budget exceeded'
      if (quota && cause instanceof ApiError && cause.status === 429) {
        error.value = `本日のチャットの上限に達しました。${formatDailyQuotaReset()} にリセットされます。`
      } else if (quota && cause instanceof ApiError && cause.status === 503) {
        error.value = '今月のチャットの上限に達しました。翌月にもう一度お試しください。'
      } else error.value = cause instanceof Error ? cause.message : '回答を取得できませんでした。'
    }
  } finally {
    clearTimeout(deadline)
    if (currentGeneration === generation) {
      busy.value = false
      activeRequest = null
      activeDeadline = null
    }
  }
}
</script>

<template>
  <section class="mt-6 rounded-lg border border-stone-700 bg-stone-800 p-4" aria-labelledby="drink-log-chat-title">
    <div class="flex items-center justify-between gap-3">
      <h2 id="drink-log-chat-title" class="text-lg font-semibold text-amber-200">記録について聞く</h2>
      <button type="button" aria-label="会話をリセット" class="rounded-md px-2 py-1 text-sm text-stone-300 hover:bg-stone-700" @click="reset">新しい会話</button>
    </div>
    <p class="mt-1 text-sm text-stone-300">銘柄や最近の一杯を調べられます。会話はこのページを開いている間だけ保持します。</p>
    <ol class="mt-4 space-y-3" aria-label="チャットの会話" aria-live="polite">
      <li v-for="(message, index) in messages" :key="index" class="whitespace-pre-wrap break-words rounded-md p-3" :class="message.role === 'user' ? 'bg-stone-700 text-amber-100' : 'bg-stone-900 text-stone-200'">
        <p class="mb-1 text-xs text-stone-400">{{ message.role === 'user' ? 'あなた' : 'アシスタント' }}</p>
        {{ message.text }}
      </li>
    </ol>
    <p v-if="busy" role="status" class="mt-3 text-sm text-amber-300">回答を準備しています…</p>
    <p v-if="error" role="alert" class="mt-3 text-sm text-red-200">{{ error }}</p>
    <form class="mt-4" @submit.prevent="send">
      <label for="drink-log-chat-input" class="text-sm text-amber-200">質問</label>
      <textarea id="drink-log-chat-input" v-model="input" rows="2" maxlength="4000" placeholder="例: 最近飲んだアランを教えて" class="mt-1 block w-full rounded-md border-amber-700 bg-stone-700 text-amber-100 placeholder:text-stone-400" />
      <p class="mt-1 text-xs text-stone-400">{{ Array.from(input).length }} / 2000文字</p>
      <button type="submit" :disabled="busy || !input.trim()" class="mt-3 rounded-md border border-amber-700 bg-amber-800 px-4 py-2 text-amber-100 hover:bg-amber-700 disabled:opacity-50">送信</button>
    </form>
  </section>
</template>
