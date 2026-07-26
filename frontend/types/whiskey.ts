export const SERVING_STYLES = ['NEAT', 'ROCKS', 'WATER', 'SODA', 'COCKTAIL'] as const

export type ServingStyle = typeof SERVING_STYLES[number]

export interface Whiskey {
  id: string
  name: string
  name_en?: string
  name_ja?: string
  distillery: string
  region?: string
  type?: string
  description?: string
  created_at?: string
  updated_at?: string
}

export interface CursorParams {
  limit?: number
  next_token?: string | null
}

export interface CursorResponse<T> {
  results?: T[]
  whiskeys?: T[]
  count: number
  next_token: string | null
}
