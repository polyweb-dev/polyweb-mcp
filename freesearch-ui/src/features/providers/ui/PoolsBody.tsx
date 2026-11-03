import type { PoolsController } from "../model/usePoolsController"
import { PoolsTable } from "./PoolsTable"
import { NOTE_CLASS } from "./formStyles"

/** Load state and table of the pools; without pool management only a note. */
export function PoolsBody({ controller, canManage }: { controller: PoolsController; canManage: boolean }) {
  const { pools } = controller
  if (!canManage) return <p role="note" className={NOTE_CLASS}>Only a pool administrator can view pools.</p>
  if (pools.status === "loading") return <p role="status" className={NOTE_CLASS}>Loading pools…</p>
  if (pools.status === "error") return <p role="alert" className={NOTE_CLASS}>The pools could not be loaded.</p>
  return (
    <PoolsTable pools={pools.data} canManage={canManage} onEdit={controller.openForm} onLinks={controller.openLinks} />
  )
}
