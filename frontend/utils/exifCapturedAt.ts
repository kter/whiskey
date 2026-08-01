interface ExifDateParts {
  year: number
  month: number
  day: number
  hour: number
  minute: number
  second: number
  millisecond: number
}

const EARLIEST_CAPTURED_AT = Date.UTC(2000, 0, 1)
const MAX_FUTURE_MILLISECONDS = 5 * 60 * 1000

const pad = (value: number) => String(value).padStart(2, '0')

const validParts = (parts: ExifDateParts) => {
  const daysInMonth = new Date(Date.UTC(parts.year, parts.month, 0)).getUTCDate()
  return parts.year >= 1
    && parts.month >= 1
    && parts.month <= 12
    && parts.day >= 1
    && parts.day <= daysInMonth
    && parts.hour >= 0
    && parts.hour <= 23
    && parts.minute >= 0
    && parts.minute <= 59
    && parts.second >= 0
    && parts.second <= 59
}

const dateParts = (value: unknown): ExifDateParts | null => {
  if (value instanceof Date) {
    if (Number.isNaN(value.getTime())) return null
    return {
      year: value.getFullYear(),
      month: value.getMonth() + 1,
      day: value.getDate(),
      hour: value.getHours(),
      minute: value.getMinutes(),
      second: value.getSeconds(),
      millisecond: value.getMilliseconds(),
    }
  }
  if (typeof value !== 'string') return null
  const match = /^(\d{4})[:-](\d{2})[:-](\d{2})[ T](\d{2}):(\d{2}):(\d{2})(?:\.(\d+))?$/.exec(value.trim())
  if (!match) return null
  const parts = {
    year: Number(match[1]),
    month: Number(match[2]),
    day: Number(match[3]),
    hour: Number(match[4]),
    minute: Number(match[5]),
    second: Number(match[6]),
    millisecond: Number((match[7] || '').slice(0, 3).padEnd(3, '0')),
  }
  return validParts(parts) ? parts : null
}

const exifOffset = (value: unknown) => {
  if (value === 'Z') return { text: 'Z', minutes: 0 }
  if (typeof value !== 'string') return null
  const match = /^([+-])(\d{2}):?(\d{2})$/.exec(value.trim())
  if (!match) return null
  const hours = Number(match[2])
  const minutes = Number(match[3])
  if (hours > 23 || minutes > 59) return null
  const direction = match[1] === '+' ? 1 : -1
  return {
    text: `${match[1]}${pad(hours)}:${pad(minutes)}`,
    minutes: direction * (hours * 60 + minutes),
  }
}

const wallClock = (parts: ExifDateParts) => (
  `${String(parts.year).padStart(4, '0')}-${pad(parts.month)}-${pad(parts.day)}`
  + `T${pad(parts.hour)}:${pad(parts.minute)}:${pad(parts.second)}`
)

const capturedAt = (value: unknown, rawOffset: unknown): string | null => {
  const parts = dateParts(value)
  if (!parts) return null
  const offset = exifOffset(rawOffset)
  let instant: number
  let offsetText: string

  if (rawOffset !== undefined && rawOffset !== null && !offset) return null
  if (offset) {
    instant = Date.UTC(
      parts.year,
      parts.month - 1,
      parts.day,
      parts.hour,
      parts.minute,
      parts.second,
      parts.millisecond,
    ) - offset.minutes * 60 * 1000
    offsetText = offset.text
  } else {
    const local = new Date(
      parts.year,
      parts.month - 1,
      parts.day,
      parts.hour,
      parts.minute,
      parts.second,
      parts.millisecond,
    )
    if (
      local.getFullYear() !== parts.year
      || local.getMonth() !== parts.month - 1
      || local.getDate() !== parts.day
      || local.getHours() !== parts.hour
      || local.getMinutes() !== parts.minute
      || local.getSeconds() !== parts.second
    ) return null
    instant = local.getTime()
    const localOffsetMinutes = -local.getTimezoneOffset()
    const sign = localOffsetMinutes >= 0 ? '+' : '-'
    const absoluteOffset = Math.abs(localOffsetMinutes)
    offsetText = `${sign}${pad(Math.floor(absoluteOffset / 60))}:${pad(absoluteOffset % 60)}`
  }

  if (
    !Number.isFinite(instant)
    || instant < EARLIEST_CAPTURED_AT
    || instant > Date.now() + MAX_FUTURE_MILLISECONDS
  ) return null
  return `${wallClock(parts)}${offsetText}`
}

/** 元ファイルの EXIF から撮影日時を読む。無い/不正なら null。 */
export const readExifCapturedAt = async (file: File): Promise<string | null> => {
  try {
    const exifr = (await import('exifr')).default
    const metadata = await exifr.parse(file, {
      exif: true,
      gps: false,
      pick: ['DateTimeOriginal', 'OffsetTimeOriginal', 'CreateDate'],
      reviveValues: false,
    }) as Record<string, unknown> | undefined
    if (!metadata) return null
    return capturedAt(metadata.DateTimeOriginal ?? metadata.CreateDate, metadata.OffsetTimeOriginal)
  } catch {
    return null
  }
}
