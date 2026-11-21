import { useCallback, useEffect, useRef, useState } from 'react'
import { errorMessage } from '../services/api'

export interface AsyncState<T> { data: T | null; error: string; loading: boolean; reload: () => void }

/** Runs an api call on mount and whenever `deps` change. Ignores results of superseded calls. */
export function useAsync<T>(loader: () => Promise<T>, deps: unknown[]): AsyncState<T> {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [tick, setTick] = useState(0)
  const loaderRef = useRef(loader)
  loaderRef.current = loader
  useEffect(() => {
    let active = true
    setLoading(true)
    setError('')
    loaderRef.current().then((value) => { if (active) { setData(value); setLoading(false) } }).catch((reason) => { if (active) { setError(errorMessage(reason)); setLoading(false) } })
    return () => { active = false }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick])
  const reload = useCallback(() => setTick((value) => value + 1), [])
  return { data, error, loading, reload }
}
