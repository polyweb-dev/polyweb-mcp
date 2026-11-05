import { useMemo, useState } from "react"
import {
  PROJECT_PERMISSIONS,
  hasPermission,
  useProjectScope,
  useProjects,
} from "@/domains/projects"
import { SETTINGS_SECTIONS, tracePolicySummary } from "@/domains/settings"
import { Button } from "@/shared/ui/button"
import {
  SETTINGS_CONFLICT,
  useProjectSettingsController,
} from "../model/useProjectSettingsController"
import { CopySettingsDialog } from "./CopySettingsDialog"
import { SettingsSection } from "./SettingsSection"

const READ_ONLY_NOTE = "You can view these settings. Ask a project administrator to change them."
const NOTE_CLASS = "text-[13px] text-[var(--muted)]"

/**
 * Settings of one project (`settings.read`, gated by the shell).
 *
 * Fields are editable only with `settings.write` and where the system allows
 * an override. Copy needs `settings.copy` and `settings.write`.
 */
export function ProjectSettingsPage({ accountId }: { accountId: string }) {
  const { projectId, accessState } = useProjectScope()
  const { projects } = useProjects()
  const access = accessState.status === "ready" ? accessState.data : null
  const canWrite = hasPermission(access, PROJECT_PERMISSIONS.settingsWrite)
  const canCopy = canWrite && hasPermission(access, PROJECT_PERMISSIONS.settingsCopy)
  const controller = useProjectSettingsController({ accountId, projectId })
  const [copying, setCopying] = useState(false)
  const { settings } = controller
  const sources = useMemo(() => projects.filter((project) => project.id !== projectId), [projects, projectId])
  const copyTarget = useMemo(() => ({ projectId, onApplied: controller.replace }), [projectId, controller.replace])

  return (
    <section className="flex flex-1 flex-col space-y-6">
      <div className="mb-6 flex items-end justify-between gap-4 border-b border-[var(--border-subtle)] pb-3">
        <div className="min-w-0">
          <h2 className="text-xl font-medium text-[var(--text-strong)]">Settings</h2>
          <p className="mt-0.5 truncate text-[13px] text-[var(--muted)]">Routing, execution and trace policy of this project.</p>
        </div>
        {canCopy && <Button size="form" variant="outline" onClick={() => setCopying(true)}>Copy from another project</Button>}
      </div>

      {!canWrite && <p role="note" className={NOTE_CLASS}>{READ_ONLY_NOTE}</p>}
      {controller.conflict && (
        <div role="alert" className="flex items-center gap-3 text-[13px] text-[var(--status-danger)]">
          <span>{SETTINGS_CONFLICT}</span>
          <Button size="form" variant="outline" onClick={controller.reload}>Reload settings</Button>
        </div>
      )}
      {controller.message !== null && <p role="alert" className="text-[13px] text-[var(--status-danger)]">{controller.message}</p>}
      {controller.notice !== null && <p role="status" className="text-[13px] text-[var(--text)]">{controller.notice}</p>}

      {settings.status === "loading" && <p role="status" className={NOTE_CLASS}>Loading settings…</p>}
      {settings.status === "error" && <p role="alert" className={NOTE_CLASS}>The settings could not be loaded.</p>}
      {settings.status === "ready" &&
        SETTINGS_SECTIONS.map((section) => (
          <SettingsSection
            key={section}
            section={section}
            fields={settings.data.fields}
            revision={settings.data.projectRevision}
            editable={canWrite}
            controller={controller}
          >
            {section === "trace" && (
              <p data-testid="trace-policy-summary" className="text-[13px] text-[var(--text)]">
                {tracePolicySummary(settings.data.fields)}
              </p>
            )}
          </SettingsSection>
        ))}

      {canCopy && (
        <CopySettingsDialog open={copying} target={copyTarget} sources={sources} onClose={() => setCopying(false)} />
      )}
    </section>
  )
}
