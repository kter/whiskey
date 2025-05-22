import { ref } from 'vue'
import type { Review, ReviewInput, ReviewSearchParams, RankingItem } from '~/types/whiskey'
import { useAuth } from '~/composables/useAuth'

export const useWhiskeys = () => {
  const { getToken } = useAuth()
  const config = useRuntimeConfig()

  const reviews = ref<Review[]>([])
  const loading = ref(false)
  const error = ref<string | null>(null)
  const totalCount = ref(0)

  // レビュー一覧の取得
  const fetchReviews = async (params: ReviewSearchParams) => {
    try {
      loading.value = true
      error.value = null

      const token = await getToken()
      const response = await fetch(
        `${config.public.apiBaseUrl}/api/reviews?${new URLSearchParams(params as any)}`,
        {
          headers: {
            Authorization: `Bearer ${token}`
          }
        }
      )

      if (!response.ok) {
        throw new Error('レビューの取得に失敗しました')
      }

      const data = await response.json()
      reviews.value = data.reviews
      totalCount.value = data.total_count
    } catch (err) {
      error.value = 'レビューの取得に失敗しました'
      throw err
    } finally {
      loading.value = false
    }
  }

  // レビューの作成
  const createReview = async (review: ReviewInput) => {
    try {
      loading.value = true
      error.value = null

      const token = await getToken()
      const response = await fetch(`${config.public.apiBaseUrl}/api/reviews`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`
        },
        body: JSON.stringify(review)
      })

      if (!response.ok) {
        throw new Error('レビューの作成に失敗しました')
      }

      return await response.json()
    } catch (err) {
      error.value = 'レビューの作成に失敗しました'
      throw err
    } finally {
      loading.value = false
    }
  }

  // レビューの更新
  const updateReview = async (id: number, review: ReviewInput) => {
    try {
      loading.value = true
      error.value = null

      const token = await getToken()
      const response = await fetch(`${config.public.apiBaseUrl}/api/reviews/${id}`, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`
        },
        body: JSON.stringify(review)
      })

      if (!response.ok) {
        throw new Error('レビューの更新に失敗しました')
      }

      return await response.json()
    } catch (err) {
      error.value = 'レビューの更新に失敗しました'
      throw err
    } finally {
      loading.value = false
    }
  }

  // レビューの削除
  const deleteReview = async (id: number) => {
    try {
      loading.value = true
      error.value = null

      const token = await getToken()
      const response = await fetch(`${config.public.apiBaseUrl}/api/reviews/${id}`, {
        method: 'DELETE',
        headers: {
          Authorization: `Bearer ${token}`
        }
      })

      if (!response.ok) {
        throw new Error('レビューの削除に失敗しました')
      }
    } catch (err) {
      error.value = 'レビューの削除に失敗しました'
      throw err
    } finally {
      loading.value = false
    }
  }

  // ランキングの取得
  const fetchRanking = async (): Promise<RankingItem[]> => {
    try {
      loading.value = true
      error.value = null

      const token = await getToken()
      const response = await fetch(`${config.public.apiBaseUrl}/api/reviews/ranking`, {
        headers: {
          Authorization: `Bearer ${token}`
        }
      })

      if (!response.ok) {
        throw new Error('ランキングの取得に失敗しました')
      }

      return await response.json()
    } catch (err) {
      error.value = 'ランキングの取得に失敗しました'
      throw err
    } finally {
      loading.value = false
    }
  }

  return {
    reviews,
    loading,
    error,
    totalCount,
    fetchReviews,
    createReview,
    updateReview,
    deleteReview,
    fetchRanking
  }
} 