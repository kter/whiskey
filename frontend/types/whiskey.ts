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
  id: number
  whiskey_name: string
  distillery?: string
  notes?: string
  rating: number
  style: ServingStyle[]
  date: string
  image_url?: string
  created_at: string
  updated_at: string
}

export type ReviewInput = Omit<Review, 'id' | 'created_at' | 'updated_at'>

export interface RankingItem {
  id: number
  name: string
  distillery: string
  avg_rating: number
  review_count: number
}

export interface AlcoholStats {
  total_volume_ml: number
  daily_average_ml: number
  max_daily_volume_ml: number
}

export interface ChartDataPoint {
  date: string
  volume_ml: number
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