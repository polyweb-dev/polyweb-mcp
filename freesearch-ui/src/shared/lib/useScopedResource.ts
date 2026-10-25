import { useCallback, useEffect, useMemo, useRef, useState } from "react"

/**
 * Load state of one scope-bound resource.
 *
 * The union is discriminated on `status`, so a consumer can never read `data`
 * while the scope still loads or `error` while the last load succeeded.
 */
export type ScopedResourceState<T> =
  | { status: "loading" }
  | { status: "ready"; data: T }
  | { status: "error"; error: unknown }

/** Options of one scope-bound load. */
export interface UseScopedResourceOptions<T> {
  /**
   * Identity of the scope (account, project, …). A change aborts the in-flight
   * request, stops the poll, and drops every late result of the old scope.
   */
  scopeKey: string
  /** Load the resource; the signal aborts when the scope closes or re-loads. */
  load: (signal: AbortSignal) => Promise<T>
  /** Optional poll interval; window focus re-loads as well when set. */
  pollMs?: number
  /** Gate the load without unmounting the hook. */
  enabled?: boolean
}

/** Scoped resource: the discriminated state plus a manual reload. */
export type ScopedResource<T> = ScopedResourceState<T> & {
  reload: () => Promise<T | undefined>
}

const LOADING: ScopedResourceState<never> = { status: "loading" }

interface Snapshot<T> {
  scopeKey: string
  inner: ScopedResourceState<T>
}

/**
 * Load one resource bound to `scopeKey` with strict stale-result hygiene.
 *
 * A generation counter decides freshness: any resolve or reject whose
 * generation no longer matches is ignored before it can touch state, so a
 * slow response of a previous scope can never overwrite the current one. The
 * same effect aborts the previous request and clears the previous interval,
 * which keeps a project switch free of late writes and orphan polls. The
 * rendered state derives from the stored scope key, so a scope change shows
 * `loading` immediately without a cascading render.
 */
export function useScopedResource<T>(options: UseScopedResourceOptions<T>): ScopedResource<T> {
  const { scopeKey, load, pollMs, enabled = true } = options
  const [snapshot, setSnapshot] = useState<Snapshot<T>>({ scopeKey, inner: LOADING })
  const generationRef = useRef(0)
  const activeRef = useRef<{ generation: number; scopeKey: string } | null>(null)
  const controllerRef = useRef<AbortController | null>(null)
  const loadRef = useRef(load)

  useEffect(() => {
    loadRef.current = load
  })

  const run = useCallback(
    async (generation: number, activeScope: string): Promise<T | undefined> => {
      if (generationRef.current !== generation) return undefined
      controllerRef.current?.abort()
      const controller = new AbortController()
      controllerRef.current = controller
      try {
        const data = await loadRef.current(controller.signal)
        if (generationRef.current !== generation || controller.signal.aborted) {
          return undefined
        }
        setSnapshot({ scopeKey: activeScope, inner: { status: "ready", data } })
        return data
      } catch (error) {
        if (generationRef.current !== generation || controller.signal.aborted) {
          return undefined
        }
        setSnapshot({ scopeKey: activeScope, inner: { status: "error", error } })
        return undefined
      }
    },
    []
  )

  useEffect(() => {
    generationRef.current += 1
    const generation = generationRef.current
    controllerRef.current = null
    if (!enabled) {
      activeRef.current = null
      return () => {
        generationRef.current += 1
      }
    }
    activeRef.current = { generation, scopeKey }
    void run(generation, scopeKey)
    let interval: number | undefined
    const onFocus = () => {
      void run(generation, scopeKey)
    }
    if (pollMs !== undefined && pollMs > 0) {
      interval = window.setInterval(() => {
        void run(generation, scopeKey)
      }, pollMs)
      window.addEventListener("focus", onFocus)
    }
    return () => {
      generationRef.current += 1
      activeRef.current = null
      controllerRef.current?.abort()
      controllerRef.current = null
      if (interval !== undefined) window.clearInterval(interval)
      window.removeEventListener("focus", onFocus)
    }
  }, [scopeKey, pollMs, enabled, run])

  const reload = useCallback((): Promise<T | undefined> => {
    const active = activeRef.current
    if (active === null || active.scopeKey !== scopeKey) {
      return Promise.resolve(undefined)
    }
    return run(active.generation, active.scopeKey)
  }, [run, scopeKey])

  const state: ScopedResourceState<T> =
    enabled && snapshot.scopeKey === scopeKey ? snapshot.inner : LOADING
  return useMemo(() => ({ ...state, reload }) as ScopedResource<T>, [state, reload])
}
