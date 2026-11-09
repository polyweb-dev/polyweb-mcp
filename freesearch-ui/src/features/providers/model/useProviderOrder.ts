import { useCallback, useEffect, useRef, useState } from "react"
import { getProjectOrder, putProjectOrder } from "@/domains/routing"
import type { OrderOperation, OrderStrategy, OrderUpdate, ProjectOrder } from "@/domains/routing"
import { ApiError, errorMessage } from "@/shared/api/http"
import { useNotifications } from "@/shared/notifications/useNotifications"

type LoadState = { status: "loading" } | { status: "error" } | { status: "ready"; data: ProjectOrder }
type UndoState = { operation: OrderOperation; strategy: OrderStrategy }

export function useProviderOrder(projectId: string, revision = 0) {
  const [state, setState] = useState<LoadState>({ status: "loading" })
  const [pending, setPending] = useState(false)
  const [undo, setUndo] = useState<UndoState | null>(null)
  const { showToast } = useNotifications()
  const generation = useRef(0)
  const busy = useRef(false)
  const mounted = useRef(false)

  useEffect(() => {
    if (undo === null) return
    const timer = window.setTimeout(() => setUndo(null), 10_000)
    return () => window.clearTimeout(timer)
  }, [undo])

  const load = useCallback(async () => {
    const current = ++generation.current
    try {
      const data = await getProjectOrder(projectId)
      if (current === generation.current) setState({ status: "ready", data })
    } catch {
      if (current === generation.current) setState({ status: "error" })
    }
  }, [projectId])

  useEffect(() => {
    mounted.current = true
    const current = ++generation.current
    void getProjectOrder(projectId).then(
      (data) => { if (current === generation.current) setState({ status: "ready", data }) },
      () => { if (current === generation.current) setState({ status: "error" }) },
    )
    return () => { mounted.current = false; generation.current += 1 }
  }, [projectId, revision])

  const reload = useCallback(async () => {
    setState({ status: "loading" })
    await load()
  }, [load])

  const save = useCallback(async (operation: OrderOperation, update: OrderUpdate, previous: OrderStrategy | null) => {
    if (busy.current) return
    busy.current = true
    setPending(true)
    const current = generation.current
    try {
      const data = await putProjectOrder(projectId, operation, update)
      if (current !== generation.current) return
      setState({ status: "ready", data })
      setUndo(previous === null ? null : { operation, strategy: previous })
    } catch (error) {
      if (current !== generation.current) return
      if (error instanceof ApiError && error.status === 409) {
        setUndo(null)
        showToast("The providers changed. The list is reloaded.", "error")
        await reload()
      } else {
        showToast(`The server did not save the order. ${errorMessage(error, "")}`.trim(), "error")
      }
    } finally {
      busy.current = false
      if (mounted.current) setPending(false)
    }
  }, [projectId, reload, showToast])

  return { state, pending, undo, reload, save }
}
