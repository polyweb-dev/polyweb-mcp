import { useMemo, useState } from "react"
import {
  PROJECT_PERMISSIONS,
  hasPermission,
  useProjectScope,
  useProjects,
} from "@/domains/projects"
import { Button } from "@/shared/ui/button"
import { PageHeader } from "@/shared/ui/PageHeader"
import {
  SETTINGS_CONFLICT,
  useProjectSettingsController,
} from "../model/useProjectSettingsController"
import { VISIBLE_SECTIONS } from "../model/visibleSections"
import { CopySettingsDialog } from "./CopySettingsDialog"
import { SettingsSaveBar } from "./SettingsSaveBar"
import { SettingsSection } from "./SettingsSection"

const READ_ONLY_NOTE = "Ask a project admin to change this"
const NOTE_CLASS = "text-[13px] text-[var(--muted)]"

/**
 * Settings of one project (`settings.read`, gated by the shell).
 *
 * Only the sections dispatch applies are shown (`VISIBLE_SECTIONS`). Fields
 * are editable only with `settings.write` and where the system allows an
 * override; one save bar writes every change at once. Copy needs
 * `settings.copy` and `settings.write`.
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
      <PageHeader
        title="Settings"
        description={<>What this project stores for each call{!canWrite && <> · <span>{READ_ONLY_NOTE}</span></>}</>}
        {...(canCopy
          ? {
              actions: (
                <Button size="sm" variant="outline" onClick={() => setCopying(true)}>
                  Copy from another project
                </Button>
              ),
            }
          : {})}
      />

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
      {settings.status === "ready" && (
        <div className="space-y-8 pb-20">
          {VISIBLE_SECTIONS.map((section) => (
            <SettingsSection
              key={section}
              section={section}
              fields={settings.data.fields}
              editable={canWrite}
              controller={controller}
            />
          ))}
        </div>
      )}

      <SettingsSaveBar
        changeCount={controller.changeCount}
        invalidCount={controller.invalidCount}
        pending={controller.pending}
        onDiscard={controller.discard}
        onSave={() => void controller.save()}
      />

      {canCopy && (
        <CopySettingsDialog open={copying} target={copyTarget} sources={sources} onClose={() => setCopying(false)} />
      )}
    </section>
  )
}
