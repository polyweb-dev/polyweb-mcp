import type { Project } from "@/domains/projects"
import type { Pool } from "@/domains/providers"
import { Button } from "@/shared/ui/button"
import { Modal } from "@/shared/ui/Modal"
import { useAllocationsController } from "../model/useAllocationsController"
import { AllocationForm } from "./AllocationForm"
import { AllocationsBody } from "./AllocationsBody"
import { ALERT_CLASS, FIELD_CLASS, LABEL_CLASS } from "./formStyles"

interface AllocationsSectionProps {
  projects: readonly Project[]
  pools: readonly Pool[]
  /** Caller holds `system.allocations.manage`. */
  canManage: boolean
}

/** Per-project allocations; editable only with allocation management. */
export function AllocationsSection({ projects, pools, canManage }: AllocationsSectionProps) {
  const controller = useAllocationsController(projects[0]?.id ?? "")
  const { editing } = controller

  return (
    <section aria-labelledby="project-allocations" className="space-y-3">
      <div className="flex items-end justify-between gap-4">
        <h2 id="project-allocations" className="text-[var(--text-strong)]">Project allocations</h2>
        {canManage && controller.projectId !== "" && (
          <Button size="sm" onClick={() => controller.openForm("new")}>Add allocation</Button>
        )}
      </div>
      <div className="max-w-sm">
        <label htmlFor="allocation-project" className={LABEL_CLASS}>Project</label>
        <select id="allocation-project" value={controller.projectId} onChange={(event) => controller.setProjectId(event.target.value)} className={FIELD_CLASS}>
          {projects.map((project) => (<option key={project.id} value={project.id}>{project.name}</option>))}
        </select>
      </div>
      {controller.message !== null && <p role="alert" className={ALERT_CLASS}>{controller.message}</p>}
      <AllocationsBody controller={controller} pools={pools} canManage={canManage} />
      <Modal isOpen={editing !== null} onClose={() => controller.openForm(null)} title={editing === "new" ? "Add allocation" : "Edit allocation"} maxWidth="2xl">
        {editing !== null && (
          <AllocationForm
            allocation={editing === "new" ? null : editing}
            pools={pools}
            pending={controller.pending}
            error={controller.formError}
            onSubmit={controller.save}
            onCancel={() => controller.openForm(null)}
          />
        )}
      </Modal>
    </section>
  )
}
