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
/** Reserved for the JWT that the backend will issue once /auth/login exists (SRS Table 9). */
export const setAuthToken = (token: string | null) => { authToken = token }

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

export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const url = new URL(`${API_URL}${path}`)
  Object.entries(options.query ?? {}).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') url.searchParams.set(key, String(value))
  })
  const headers: Record<string, string> = { Accept: 'application/json' }
  if (options.body !== undefined) headers['Content-Type'] = 'application/json'
  if (authToken) headers.Authorization = `Bearer ${authToken}`
  let response: Response
  try {
    response = await fetch(url.toString(), { method: options.method ?? 'GET', headers, body: options.body === undefined ? undefined : JSON.stringify(options.body) })
  } catch {
    throw new ApiError(0, `Cannot reach the ATES server at ${API_URL}. Check that it is running and that VITE_API_URL is correct.`)
  }
  const text = response.status === 204 ? '' : await response.text()
  let body: unknown = null
  if (text) { try { body = JSON.parse(text) } catch { body = text } }
  if (!response.ok && !(options.passthrough ?? []).includes(response.status)) {
    throw new ApiError(response.status, describeDetail(body, `Request failed with status ${response.status}.`), body)
  }
  if (!response.ok) return { __status: response.status, ...(body as object) } as T
  return body as T
}
