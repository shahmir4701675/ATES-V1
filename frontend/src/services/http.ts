/** Low-level HTTP helper. Only the api module may import this file; components never call fetch. */

export const API_URL = (import.meta.env.VITE_API_URL ?? 'http://localhost:8000').replace(/\/+$/, '')
/** Flag to switch the whole api module back to in-memory mock data. */
export const USE_MOCK = String(import.meta.env.VITE_USE_MOCK ?? 'false').toLowerCase() === 'true'

export class ApiError extends Error {
  status: number
  body: unknown
  constructor(status: number, message: string, body?: unknown) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.body = body
  }
}

let authToken: string | null = null
let authEpoch = 0
let readEpoch = 0
interface ResponseData { body: unknown; total: number | null }
const pendingReads = new Map<string, Promise<ResponseData>>()
const invalidateReads = () => { readEpoch += 1; pendingReads.clear() }
/** Keep bearer credentials in memory; a reload requires signing in again. */
export const setAuthToken = (token: string | null) => { authToken = token; authEpoch += 1; invalidateReads() }

/** FastAPI returns `detail` as a string, or as a list of { loc, msg } for 422 validation errors. */
export function describeDetail(body: unknown, fallback: string): string {
  const detail = (body as { detail?: unknown } | null)?.detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    return detail.map((item: { loc?: unknown[]; msg?: string }) => {
      const field = Array.isArray(item.loc) ? item.loc.filter((part) => part !== 'body').join('.') : ''
      return field ? `${field}: ${item.msg ?? 'invalid value'}` : item.msg ?? 'invalid value'
    }).join('; ')
  }
  return fallback
}

export interface RequestOptions {
  method?: 'GET' | 'POST' | 'PUT' | 'DELETE'
  body?: unknown
  query?: Record<string, string | number | boolean | undefined | null>
  /** Treat these statuses as data instead of errors (e.g. 409 on a manual move). */
  passthrough?: number[]
}

async function performRequest(path: string, options: RequestOptions, session: number): Promise<ResponseData> {
  const url = new URL(`${API_URL}${path}`)
  Object.entries(options.query ?? {}).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') url.searchParams.set(key, String(value))
  })
  const headers: Record<string, string> = { Accept: 'application/json' }
  const multipart = options.body instanceof FormData
  if (options.body !== undefined && !multipart) headers['Content-Type'] = 'application/json'
  if (authToken) headers.Authorization = `Bearer ${authToken}`
  let response: Response
  try {
    response = await fetch(url.toString(), { method: options.method ?? 'GET', headers, cache: 'no-store', body: options.body === undefined ? undefined : multipart ? options.body as FormData : JSON.stringify(options.body) })
  } catch {
    throw new ApiError(0, `Cannot reach the ATES server at ${API_URL}. Check that it is running and that VITE_API_URL is correct.`)
  }
  if (session !== authEpoch) throw new ApiError(401, 'The signed-in session changed while loading. Retry from the current account.')
  const text = response.status === 204 ? '' : await response.text()
  if (session !== authEpoch) throw new ApiError(401, 'The signed-in session changed while loading. Retry from the current account.')
  let body: unknown = null
  if (text) { try { body = JSON.parse(text) } catch { body = text } }
  if (response.status === 401 && path !== '/auth/login') {
    setAuthToken(null)
    window.dispatchEvent(new Event('ates:auth-required'))
  }
  if (!response.ok && !(options.passthrough ?? []).includes(response.status)) {
    throw new ApiError(response.status, describeDetail(body, `Request failed with status ${response.status}.`), body)
  }
  const totalHeader = response.headers.get('X-Total-Count')
  const total = totalHeader !== null && /^\d+$/.test(totalHeader) ? Number(totalHeader) : null
  return { body: !response.ok ? { __status: response.status, ...(body as object) } : body, total }
}

async function readResponse(path: string, options: RequestOptions): Promise<ResponseData> {
  const method = options.method ?? 'GET'
  if (method !== 'GET') {
    invalidateReads()
    try { return await performRequest(path, options, authEpoch) }
    finally { invalidateReads() }
  }
  // Share only simultaneous reads. Every later read still reaches server RBAC,
  // revocation and snapshot checks; no private response survives as a TTL cache.
  const key = JSON.stringify([authEpoch, readEpoch, path, options.query ?? {}, options.passthrough ?? []])
  let pending = pendingReads.get(key)
  if (!pending) {
    pending = performRequest(path, options, authEpoch)
    if (pendingReads.size < 128) {
      pendingReads.set(key, pending)
      const current = pending
      void pending.finally(() => { if (pendingReads.get(key) === current) pendingReads.delete(key) }).catch(() => {})
    }
  }
  const result = await pending
  return { ...result, body: structuredClone(result.body) }
}

export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  return (await readResponse(path, options)).body as T
}

export interface PageResult<T> { items: T[]; total: number }
export async function requestPage<T>(path: string, options: RequestOptions = {}): Promise<PageResult<T>> {
  const response = await readResponse(path, options)
  const items = response.body as T[]
  return { items, total: response.total ?? items.length }
}

/** Authenticated binary response; never turn a JSON error into a downloaded file. */
export async function requestDownload(path: string, query: RequestOptions['query'] = {}): Promise<{ blob: Blob; filename: string }> {
  const url = new URL(`${API_URL}${path}`)
  Object.entries(query).forEach(([key, value]) => { if (value !== undefined && value !== null && value !== '') url.searchParams.set(key, String(value)) })
  const response = await fetch(url, { headers: authToken ? { Authorization: `Bearer ${authToken}` } : {} })
  if (response.status === 401) { setAuthToken(null); window.dispatchEvent(new Event('ates:auth-required')) }
  if (!response.ok) {
    const body = await response.json().catch(() => null)
    throw new ApiError(response.status, describeDetail(body, 'Export failed.'), body)
  }
  const filename = /filename="([^"]+)"/.exec(response.headers.get('Content-Disposition') ?? '')?.[1] ?? 'ates-export'
  return { blob: await response.blob(), filename }
}
