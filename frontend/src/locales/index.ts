import en from './en.json'
export type MessageKey = keyof typeof en
export const t = (key: MessageKey): string => en[key]
export const TIME_ZONE = 'Asia/Karachi'
export const utcTimestamp = (value: string): Date => new Date(/(?:Z|[+-]\d{2}:?\d{2})$/i.test(value) ? value : `${value}Z`)
export const formatTimestamp = (value: string): string => new Intl.DateTimeFormat('en-GB', { timeZone: TIME_ZONE, year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false }).format(utcTimestamp(value))
export const formatToday = (): string => new Intl.DateTimeFormat('en-GB', { timeZone: TIME_ZONE }).format(new Date())
