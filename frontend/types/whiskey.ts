export type ServingStyle =
  | 'Neat'
  | 'Rock'
  | 'Twice Up'
  | 'High Ball'
  | 'On the Rocks'
  | 'Water'
  | 'Hot'
  | 'Cocktail'

export interface Review {
  id: string
  whiskey_id?: string
  whiskey?: string
  whiskey_name?: string
  whiskey_distillery?: string
  notes?: string
  rating: number
  style?: ServingStyle[]
  serving_style?: string
  date: string
  image_url?: string
  created_at: string
  updated_at: string
  user_id?: string
}

export interface ReviewInput {
  whiskey?: string
  whiskey_name?: string
  distillery?: string
  notes?: string
  rating: number
  style?: ServingStyle[]
  serving_style?: string
  date: string
  image_url?: string
}

export interface Whiskey {
  id: string
  name: string
  distillery: string
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

export interface PaginationParams {
  page?: number
  per_page?: number
}

export interface ReviewSearchParams {
  page: number
  per_page: number
  search?: string
  sort_by?: 'date' | 'rating'
  sort_order?: 'asc' | 'desc'
}

export interface ApiError {
  code: string
  message: string
  details?: Record<string, any>
} 