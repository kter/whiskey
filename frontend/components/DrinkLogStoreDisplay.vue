<script setup lang="ts">
import { computed } from 'vue'
import type { DrinkLog, ResolvedPlace } from '~/composables/useDrinkLogs'

const props = defineProps<{
  log: DrinkLog
  resolvedPlace?: ResolvedPlace
}>()

const isGoogleName = computed(() => props.resolvedPlace?.name_source === 'google')
const displayName = computed(() => {
  if (props.log.store.name.trim()) return props.log.store.name
  if (isGoogleName.value && props.resolvedPlace?.display_name) return props.resolvedPlace.display_name
  return props.log.store.place_id ? '場所登録済み' : '場所未登録'
})
</script>

<template>
  <span class="block min-w-0">
    <span class="block truncate">{{ displayName }}</span>
    <GoogleAttributions v-if="isGoogleName" :attributions="resolvedPlace?.attributions || []" />
  </span>
</template>
