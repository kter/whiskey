export const SERVING_STYLES = ['NEAT', 'ROCKS', 'WATER', 'SODA', 'COCKTAIL'] as const

export type ServingStyle = typeof SERVING_STYLES[number]

export interface Review {
  id: string
  whiskey_id: string
  whiskey_name?: string
  whiskey_distillery?: string
  notes?: string
  rating: number
  serving_style: ServingStyle
  date: string
  is_public: boolean
  created_at: string
  updated_at: string
  user_id?: string
}

export interface ReviewInput {
  whiskey_id: string
  notes?: string
  rating: number
  serving_style: ServingStyle
  date: string
  is_public: boolean
}

export interface ReviewUpdateInput {
  notes?: string
  rating: number
  serving_style: ServingStyle
  date: string
  is_public: boolean
}

export interface Whiskey {
  id: string
  name: string
  name_en?: string
  name_ja?: string
  distillery: string
  region?: string
  type?: string
  description?: string
  avg_rating?: number
  review_count?: number
  created_at?: string
  updated_at?: string
}

export interface RankingItem {
  id: string
  name: string
  distillery: string
  avg_rating: number
  review_count: number
}

export interface CursorParams {
  limit?: number
  next_token?: string | null
}

export interface CursorResponse<T> {
  results?: T[]
  reviews?: T[]
  whiskeys?: T[]
  count: number
  next_token: string | null
}

export interface RankingResponse {
  rankings: RankingItem[]
  pagination: {
    page: number
    limit: number
    total_items: number
    total_pages: number
    has_next: boolean
    has_prev: boolean
  }
}
