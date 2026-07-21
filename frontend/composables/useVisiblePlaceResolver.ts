import { onBeforeUnmount, onMounted, ref, type ComponentPublicInstance } from 'vue'
import { useDrinkLogs, type DrinkLog, type ResolvePlaceItem, type ResolvedPlace } from '~/composables/useDrinkLogs'

const MAX_BATCH_SIZE = 10
const MAX_CONCURRENT_REQUESTS = 2

const elementFrom = (target: Element | ComponentPublicInstance | null) => {
  if (target instanceof Element) return target
  return target?.$el instanceof Element ? target.$el : null
}

export const needsPlaceResolution = (log: DrinkLog) => !log.store.name.trim() && Boolean(log.store.place_id)

export const useVisiblePlaceResolver = () => {
  const { resolvePlaces } = useDrinkLogs()
  const resolvedPlaces = ref<Record<string, ResolvedPlace>>({})
  const failedLogIds = ref<Set<string>>(new Set())
  const queued = new Map<string, ResolvePlaceItem>()
  const activeLogIds = new Set<string>()
  const elements = new Map<string, Element>()
  let observer: IntersectionObserver | null = null
  let activeRequests = 0
  let disposed = false

  const markFailed = (ids: string[]) => {
    failedLogIds.value = new Set([...failedLogIds.value, ...ids])
  }

  const pump = () => {
    if (disposed) return
    while (activeRequests < MAX_CONCURRENT_REQUESTS && queued.size) {
      const batch = [...queued.values()].slice(0, MAX_BATCH_SIZE)
      batch.forEach(item => {
        queued.delete(item.log_id)
        activeLogIds.add(item.log_id)
      })
      activeRequests += 1

      void resolvePlaces(batch).then(results => {
        if (disposed) return
        const returnedIds = new Set(results.map(result => result.log_id))
        const next = { ...resolvedPlaces.value }
        results.forEach(result => {
          if (result.name_source === 'google' && result.display_name) next[result.log_id] = result
        })
        resolvedPlaces.value = next
        markFailed(batch.filter(item => !returnedIds.has(item.log_id)).map(item => item.log_id))
      }).catch(() => {
        if (!disposed) markFailed(batch.map(item => item.log_id))
      }).finally(() => {
        batch.forEach(item => activeLogIds.delete(item.log_id))
        activeRequests = Math.max(0, activeRequests - 1)
        pump()
      })
    }
  }

  const enqueue = (items: ResolvePlaceItem[]) => {
    items.forEach(item => {
      if (
        resolvedPlaces.value[item.log_id]
        || failedLogIds.value.has(item.log_id)
        || activeLogIds.has(item.log_id)
        || queued.has(item.log_id)
      ) return
      queued.set(item.log_id, item)
    })
    pump()
  }

  const register = (target: Element | ComponentPublicInstance | null, log: DrinkLog) => {
    const previous = elements.get(log.id)
    const element = elementFrom(target)
    if (previous && previous !== element) observer?.unobserve(previous)
    if (!element || !needsPlaceResolution(log)) {
      elements.delete(log.id)
      return
    }
    elements.set(log.id, element)
    observer?.observe(element)
  }

  onMounted(() => {
    if (typeof IntersectionObserver === 'undefined') {
      enqueue([...elements.keys()].flatMap(logId => {
        const element = elements.get(logId)
        const placeId = element?.getAttribute('data-place-id')
        return placeId ? [{ log_id: logId, place_id: placeId }] : []
      }))
      return
    }

    observer = new IntersectionObserver(entries => {
      const visible = entries.flatMap(entry => {
        if (!entry.isIntersecting) return []
        const logId = entry.target.getAttribute('data-log-id')
        const placeId = entry.target.getAttribute('data-place-id')
        if (!logId || !placeId) return []
        observer?.unobserve(entry.target)
        return [{ log_id: logId, place_id: placeId }]
      })
      enqueue(visible)
    }, { rootMargin: '160px 0px' })
    elements.forEach(element => observer?.observe(element))
  })

  onBeforeUnmount(() => {
    disposed = true
    queued.clear()
    observer?.disconnect()
    observer = null
    resolvedPlaces.value = {}
    failedLogIds.value = new Set()
  })

  return { resolvedPlaces, failedLogIds, register, enqueue }
}
