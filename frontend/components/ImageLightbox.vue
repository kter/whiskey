<script setup lang="ts">
import { nextTick, onBeforeUnmount, ref, watch } from 'vue'

const props = defineProps<{
  open: boolean
  src: string
  alt: string
}>()

const emit = defineEmits<{
  'update:open': [open: boolean]
}>()

const closeButton = ref<HTMLButtonElement | null>(null)
let previouslyFocused: HTMLElement | null = null
let previousBodyOverflow = ''
let active = false

const close = () => {
  emit('update:open', false)
}

const handleKeydown = (event: KeyboardEvent) => {
  if (props.open && event.key === 'Escape') close()
}

const activate = async () => {
  if (active) return
  active = true
  previouslyFocused = document.activeElement instanceof HTMLElement
    ? document.activeElement
    : null
  previousBodyOverflow = document.body.style.overflow
  document.body.style.overflow = 'hidden'
  window.addEventListener('keydown', handleKeydown)

  await nextTick()
  if (props.open) closeButton.value?.focus()
}

const deactivate = (restoreFocus: boolean) => {
  if (!active) return
  active = false
  window.removeEventListener('keydown', handleKeydown)
  document.body.style.overflow = previousBodyOverflow

  const focusTarget = previouslyFocused
  previouslyFocused = null
  if (restoreFocus && focusTarget) {
    void nextTick(() => {
      if (!props.open && focusTarget.isConnected) focusTarget.focus()
    })
  }
}

watch(() => props.open, open => {
  if (open) void activate()
  else deactivate(true)
}, { immediate: true })

onBeforeUnmount(() => {
  deactivate(false)
})
</script>

<template>
  <div
    v-if="open"
    class="fixed inset-0 z-30 flex items-center justify-center bg-black/80 p-4"
    role="dialog"
    aria-modal="true"
    :aria-label="alt"
    @click.self="close"
  >
    <button
      ref="closeButton"
      type="button"
      aria-label="閉じる"
      class="absolute right-4 top-4 rounded-md bg-stone-900/80 px-3 py-1 text-3xl leading-none text-stone-100 hover:bg-stone-700 focus:outline-none focus:ring-2 focus:ring-amber-400"
      @click="close"
    >
      ×
    </button>
    <img :src="src" :alt="alt" class="max-h-[90vh] max-w-[90vw] object-contain" />
  </div>
</template>
