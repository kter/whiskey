import type { DrinkLog } from '~/composables/useDrinkLogs'

export interface DrinkLogDateGroup {
  key: string
  label: string
  logs: DrinkLog[]
}

const validDate = (value: string) => {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? null : date
}

export const formatLocalLogDate = (value: string, timeZone?: string) => {
  const date = validDate(value)
  if (!date) return '日時不明'
  const parts = new Intl.DateTimeFormat('ja-JP', {
    year: 'numeric',
    month: 'numeric',
    day: 'numeric',
    ...(timeZone ? { timeZone } : {}),
  }).formatToParts(date)
  const part = (type: Intl.DateTimeFormatPartTypes) => parts.find(item => item.type === type)?.value || ''
  return `${part('year')}年${part('month')}月${part('day')}日`
}

export const formatLocalLogTime = (value: string, timeZone?: string) => {
  const date = validDate(value)
  if (!date) return '時刻不明'
  return new Intl.DateTimeFormat('ja-JP', {
    hour: '2-digit',
    minute: '2-digit',
    ...(timeZone ? { timeZone } : {}),
  }).format(date)
}

export const groupDrinkLogsByLocalDate = (logs: DrinkLog[], timeZone?: string): DrinkLogDateGroup[] => {
  const groups = new Map<string, DrinkLog[]>()
  logs.forEach(log => {
    const label = formatLocalLogDate(log.datetime, timeZone)
    groups.set(label, [...(groups.get(label) || []), log])
  })
  return [...groups.entries()].map(([label, records]) => ({ key: label, label, logs: records }))
}

export const servingStyleLabel = (style?: string) => ({
  NEAT: 'ストレート',
  ROCKS: 'ロック',
  WATER: '水割り・トワイスアップ',
  SODA: 'ハイボール',
  COCKTAIL: 'カクテル',
}[style || ''] || style || '指定なし')
