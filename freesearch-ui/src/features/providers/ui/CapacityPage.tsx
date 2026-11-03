import { SYSTEM_PERMISSIONS, hasPermission, useProjects } from "@/domains/projects"
import { Button } from "@/shared/ui/button"
import { Modal } from "@/shared/ui/Modal"
import { usePoolsController } from "../model/usePoolsController"
import { AllocationsSection } from "./AllocationsSection"
import { PoolForm } from "./PoolForm"
import { PoolLinksPanel } from "./PoolLinksPanel"
import { PoolsBody } from "./PoolsBody"

/**
 * Capacity (`system.pools.manage` or `system.allocations.manage`, gated by
 * the shell): upstream pools and their credential links, and per-project
 * allocations with the shared strict / loans / best-effort explanation.
 */
export function CapacityPage() {
  const { accountId, systemAccess, projects } = useProjects()
  const canPools = hasPermission(systemAccess, SYSTEM_PERMISSIONS.poolsManage)
  const canAllocations = hasPermission(systemAccess, SYSTEM_PERMISSIONS.allocationsManage)
  const controller = usePoolsController(`${accountId}:capacity`, canPools)
  const { pools, editing, linksFor } = controller
  const poolList = pools.status === "ready" ? pools.data : []

  return (
    <section className="flex flex-1 flex-col space-y-8">
      <header className="border-b border-[var(--border-subtle)] pb-2">
        <h1 className="text-[var(--text-strong)]">Capacity</h1>
        <p className="mt-0.5 text-[13px] text-[var(--muted)]">
          Shared upstream pools and how much of each one every project may use.
        </p>
      </header>

      <section aria-labelledby="pools-heading" className="space-y-3">
        <div className="flex items-end justify-between gap-4">
          <h2 id="pools-heading" className="text-[var(--text-strong)]">Pools</h2>
          {canPools && <Button size="sm" onClick={() => controller.openForm("new")}>Add pool</Button>}
        </div>
        <PoolsBody controller={controller} canManage={canPools} />
      </section>

      <AllocationsSection projects={projects} pools={poolList} canManage={canAllocations} />

      <Modal isOpen={editing !== null} onClose={() => controller.openForm(null)} title={editing === "new" ? "Add pool" : "Edit pool"} maxWidth="2xl">
        {editing !== null && (
          <PoolForm
            pool={editing === "new" ? null : editing}
            pending={controller.pending}
            error={controller.formError}
            onSubmit={controller.save}
            onCancel={() => controller.openForm(null)}
          />
        )}
      </Modal>
      <Modal isOpen={linksFor !== null} onClose={() => controller.openLinks(null)} title="Credential links" subtitle={linksFor?.label} maxWidth="xl">
        {linksFor !== null && <PoolLinksPanel key={linksFor.id} pool={linksFor} />}
      </Modal>
    </section>
  )
}
