<script setup lang="ts">
import { onMounted } from 'vue'
import { useAuth } from '~/composables/useAuth'

const { initialize } = useAuth()
onMounted(() => void initialize())
</script>

<template>
  <div class="min-h-screen bg-amber-950">
    <NuxtLayout>
      <NuxtPage />
    </NuxtLayout>
  </div>
</template>
