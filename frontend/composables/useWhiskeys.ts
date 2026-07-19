import { ref } from 'vue'
import type {
  CursorParams,
  CursorResponse,
  RankingItem,
  RankingResponse,
  Review,
  ReviewInput,
  ReviewUpdateInput,
  Whiskey,
} from '~/types/whiskey'
import { useApi } from '~/composables/useApi'

export const useWhiskeys = () => {
  const api = useApi()
  const reviews = ref<Review[]>([])
  const whiskeys = ref<Whiskey[]>([])
  const nextToken = ref<string | null>(null)
  const loading = ref(false)
  const error = ref<string | null>(null)

  const run = async <T>(message: string, operation: () => Promise<T>): Promise<T> => {
    loading.value = true
    error.value = null
    try {
      return await operation()
    } catch (cause) {
      error.value = cause instanceof Error ? cause.message : message
      throw cause
    } finally {
      loading.value = false
    }
  }

  const applyReviewPage = (data: CursorResponse<Review>, append: boolean) => {
    const items = data.results || data.reviews || []
    reviews.value = append ? [...reviews.value, ...items] : items
    nextToken.value = data.next_token || null
    return items
  }

  const fetchReviews = (params: CursorParams = {}, append = false) => run(
    'レビューの取得に失敗しました',
    async () => applyReviewPage(await api.request<CursorResponse<Review>>('/api/reviews', {
      auth: 'required',
      query: { limit: params.limit || 10, next_token: params.next_token },
    }), append),
  )

  const fetchPublicReviews = (params: CursorParams = {}, append = false) => run(
    '公開レビューの取得に失敗しました',
    async () => applyReviewPage(await api.request<CursorResponse<Review>>('/api/reviews/public', {
      auth: 'none',
      query: { limit: params.limit || 10, next_token: params.next_token },
    }), append),
  )

  const fetchReview = (id: string) => run(
    'レビューの取得に失敗しました',
    () => api.request<Review>(`/api/reviews/${encodeURIComponent(id)}`, { auth: 'required' }),
  )

  const createReview = (review: ReviewInput) => run(
    'レビューの作成に失敗しました',
    () => api.request<Review>('/api/reviews', { method: 'POST', auth: 'required', body: review }),
  )

  const updateReview = (id: string, review: ReviewUpdateInput) => run(
    'レビューの更新に失敗しました',
    () => api.request<Review>(`/api/reviews/${encodeURIComponent(id)}`, {
      method: 'PUT',
      auth: 'required',
      body: review,
    }),
  )

  const deleteReview = (id: string) => run(
    'レビューの削除に失敗しました',
    () => api.request<void>(`/api/reviews/${encodeURIComponent(id)}`, { method: 'DELETE', auth: 'required' }),
  )

  const fetchWhiskeyList = (params: CursorParams = {}, append = false) => run(
    'ウイスキー一覧の取得に失敗しました',
    async () => {
      const data = await api.request<CursorResponse<Whiskey>>('/api/whiskeys', {
        auth: 'none',
        query: { limit: params.limit || 20, next_token: params.next_token },
      })
      const items = data.whiskeys || []
      whiskeys.value = append ? [...whiskeys.value, ...items] : items
      nextToken.value = data.next_token || null
      return items
    },
  )

  const fetchRanking = (params: { page?: number; limit?: number } = {}) => run(
    'ランキングの取得に失敗しました',
    () => api.request<RankingItem[] | RankingResponse>('/api/whiskeys/ranking', {
      auth: 'none',
      query: { page: params.page, limit: params.limit },
    }),
  )

  return {
    reviews,
    whiskeys,
    nextToken,
    loading,
    error,
    fetchReviews,
    fetchPublicReviews,
    fetchReview,
    createReview,
    updateReview,
    deleteReview,
    fetchWhiskeyList,
    fetchRanking,
  }
}
