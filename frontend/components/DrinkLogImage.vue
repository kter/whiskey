<script setup lang="ts">
import { ref, watch } from 'vue'
import { useDrinkLogs, type DrinkLog } from '~/composables/useDrinkLogs'

const props = withDefaults(defineProps<{
  log: DrinkLog
  alt: string
  imageClass?: string
  placeholderClass?: string
}>(), {
  imageClass: '',
  placeholderClass: '',
})

const emit = defineEmits<{ refreshed: [log: DrinkLog] }>()
const { getLog, upsertLog } = useDrinkLogs()
const imageUrl = ref(props.log.image_url || '')
const refreshAttempted = ref(false)
const failed = ref(!imageUrl.value)

watch(() => props.log.image_url, value => {
  if (!refreshAttempted.value && value) {
    imageUrl.value = value
    failed.value = false
  }
})

const handleImageError = async () => {
  if (refreshAttempted.value) {
    failed.value = true
    return
  }
  refreshAttempted.value = true
  try {
    const refreshed = await getLog(props.log.id)
    if (!refreshed.image_url || refreshed.image_url === imageUrl.value) throw new Error('画像URLを更新できませんでした。')
    imageUrl.value = refreshed.image_url
    upsertLog(refreshed)
    emit('refreshed', refreshed)
  } catch {
    failed.value = true
  }
}
</script>

<template>
  <div v-if="failed" :class="placeholderClass" role="img" :aria-label="`${alt}（画像を表示できません）`">
    <span class="px-3 text-center text-sm text-stone-400">画像を表示できません</span>
  </div>
  <img v-else :src="imageUrl" :alt="alt" :class="imageClass" @error="handleImageError" />
</template>
