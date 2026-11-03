import type { Pool } from "@/domains/providers"
import { isForbidden } from "@/shared/api/conflict"
import type { AllocationsController } from "../model/useAllocationsController"
import { AllocationsTable } from "./AllocationsTable"
import { NOTE_CLASS } from "./formStyles"

const FORBIDDEN_NOTE = "Only an allocation administrator can view project allocations."

interface AllocationsBodyProps {
  controller: AllocationsController
  pools: readonly Pool[]
  canManage: boolean
}

/** Load state and table of the selected project's allocations. */
export function AllocationsBody({ controller, pools, canManage }: AllocationsBodyProps) {
  const { allocations } = controller
  if (controller.projectId === "") return <p className={NOTE_CLASS}>No project to show.</p>
  if (allocations.status === "loading") {
    return <p role="status" className={NOTE_CLASS}>Loading allocations…</p>
  }
  if (allocations.status === "error") {
    return (
      <p role="alert" className={NOTE_CLASS}>
        {isForbidden(allocations.error) ? FORBIDDEN_NOTE : "The allocations could not be loaded."}
      </p>
    )
  }
  return (
    <AllocationsTable
      allocations={allocations.data}
      pools={pools}
      canManage={canManage}
      pending={controller.pending}
      onEdit={(allocation) => controller.openForm(allocation)}
      onRemove={(allocation) => void controller.remove(allocation)}
    />
  )
}
