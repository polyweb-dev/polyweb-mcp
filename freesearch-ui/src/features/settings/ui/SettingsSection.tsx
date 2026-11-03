import type { ReactNode } from "react"
import { SECTION_TITLES } from "@/domains/settings"
import type { SettingsField, SettingsSectionId } from "@/domains/settings"
import { Button } from "@/shared/ui/button"
import type { ProjectSettingsController } from "../model/useProjectSettingsController"
import { SettingsFieldRow } from "./SettingsFieldRow"

interface SettingsSectionProps {
  section: SettingsSectionId
  fields: readonly SettingsField[]
  revision: number
  editable: boolean
  controller: ProjectSettingsController
  /** Extra content under the heading (the trace policy summary). */
  children?: ReactNode
}

/** One settings section with its rows and its own Save button. */
export function SettingsSection(props: SettingsSectionProps) {
  const { section, fields, revision, editable, controller, children } = props
  const title = SECTION_TITLES[section]
  const rows = fields.filter((field) => field.section === section)
  const headingId = `settings-section-${section}`
  return (
    <section aria-labelledby={headingId} className="space-y-2">
      <div className="flex items-center justify-between">
        <h2 id={headingId} className="text-[var(--text-strong)]">
          {title}
        </h2>
        {editable && (
          <Button
            size="sm"
            disabled={controller.pending || !controller.hasChanges(section)}
            onClick={() => void controller.save(section)}
          >
            Save {title}
          </Button>
        )}
      </div>
      {children}
      <div>
        {rows.map((field) => (
          <SettingsFieldRow
            key={field.id}
            field={field}
            draft={controller.draft}
            editable={editable}
            pending={controller.pending}
            revision={revision}
            onChange={controller.setValue}
            onInherit={controller.inherit}
          />
        ))}
      </div>
    </section>
  )
}
