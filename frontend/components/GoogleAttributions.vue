<script setup lang="ts">
defineProps<{ attributions: unknown[] }>()

const attributionView = (attribution: unknown) => {
  if (typeof attribution === 'string') return { label: attribution, url: '' }
  if (!attribution || typeof attribution !== 'object') return { label: String(attribution), url: '' }
  const data = attribution as Record<string, unknown>
  const rawUrl = [data.uri, data.provider_uri, data.providerUri].find(value => typeof value === 'string')
  const labelParts = Object.entries(data)
    .filter(([key, value]) => !['uri', 'provider_uri', 'providerUri'].includes(key) && typeof value === 'string' && value.trim())
    .map(([, value]) => value as string)
  return {
    label: labelParts.join(' · ') || '提供元情報',
    url: typeof rawUrl === 'string' && rawUrl.startsWith('https://') ? rawUrl : '',
  }
}
</script>

<template>
  <span class="mt-1 block text-[11px] leading-relaxed text-stone-400">
    <span translate="no" class="mr-2 whitespace-nowrap font-sans">Google Maps</span>
    <template v-for="(attribution, index) in attributions" :key="index">
      <a
        v-if="attributionView(attribution).url"
        :href="attributionView(attribution).url"
        target="_blank"
        rel="noopener noreferrer"
        class="mr-2 underline hover:text-amber-200"
      >{{ attributionView(attribution).label }}</a>
      <span v-else class="mr-2">{{ attributionView(attribution).label }}</span>
    </template>
  </span>
</template>
