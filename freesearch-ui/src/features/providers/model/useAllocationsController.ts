import { useCallback, useState } from "react"
import { deleteAllocation, listProjectAllocations, putAllocation } from "@/domains/providers"
import type { Allocation, AllocationInput, ProviderOperation } from "@/domains/providers"
import { useScopedResource } from "@/shared/lib/useScopedResource"
import type { ScopedResource } from "@/shared/lib/useScopedResource"
import { capacityFailureMessage } from "./capacityMessages"

export interface AllocationTarget {
  poolId: string
  operation: ProviderOperation
}

export interface AllocationsController {
  projectId: string
  setProjectId: (projectId: string) => void
  allocations: ScopedResource<Allocation[]>
  pending: boolean
  message: string | null
  /** Failure inside the open allocation form (e.g. "Not feasible: …"). */
  formError: string | null
  /** Open form: `"new"`, the allocation being edited, or `null`. */
  editing: Allocation | "new" | null
  openForm: (target: Allocation | "new" | null) => void
  save: (target: AllocationTarget, input: AllocationInput) => Promise<boolean>
  remove: (allocation: Allocation) => Promise<void>
}

/**
 * Allocations of the selected project, else of `defaultProjectId`. The read
 * is bound to the project id, so switching the project aborts it and ignores
 * a late answer.
 */
export function useAllocationsController(defaultProjectId: string): AllocationsController {
  const [chosen, setProject] = useState("")
  const projectId = chosen === "" ? defaultProjectId : chosen
  const allocations = useScopedResource({
    scopeKey: `allocations:${projectId}`,
    load: (signal) => listProjectAllocations(projectId, signal),
    enabled: projectId !== "",
  })
  const reload = allocations.reload
  const [pending, setPending] = useState(false)
  const [message, setMessage] = useState<string | null>(null)
  const [formError, setFormError] = useState<string | null>(null)
  const [editing, setEditing] = useState<Allocation | "new" | null>(null)

  const setProjectId = useCallback((next: string) => {
    setProject(next)
    setEditing(null)
    setMessage(null)
  }, [])

  const openForm = useCallback((target: Allocation | "new" | null) => {
    setFormError(null)
    setEditing(target)
  }, [])

  const save = useCallback(
    async (target: AllocationTarget, input: AllocationInput) => {
      setPending(true)
      setFormError(null)
      try {
        await putAllocation({ projectId, ...target }, input)
        setEditing(null)
        void reload()
        return true
      } catch (error) {
        setFormError(capacityFailureMessage(error, "The allocation could not be saved."))
        return false
      } finally {
        setPending(false)
      }
    },
    [projectId, reload]
  )

  const remove = useCallback(
    async (allocation: Allocation) => {
      setPending(true)
      setMessage(null)
      try {
        await deleteAllocation(allocation.projectId, allocation.poolId, allocation.operation)
        void reload()
      } catch (error) {
        setMessage(capacityFailureMessage(error, "The allocation could not be removed."))
      } finally {
        setPending(false)
      }
    },
    [reload]
  )

  return {
    projectId,
    setProjectId,
    allocations,
    pending,
    message,
    formError,
    editing,
    openForm,
    save,
    remove,
  }
}
