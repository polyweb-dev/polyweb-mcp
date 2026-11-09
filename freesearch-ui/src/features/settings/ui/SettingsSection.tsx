import { SECTION_TITLES } from "@/domains/settings"
import type { SettingsField, SettingsSectionId } from "@/domains/settings"
import type { ProjectSettingsController } from "../model/useProjectSettingsController"
import { SettingsFieldRow } from "./SettingsFieldRow"

interface SettingsSectionProps {
  section: SettingsSectionId
  fields: readonly SettingsField[]
  editable: boolean
  controller: ProjectSettingsController
}

/** One settings section: its title, then one full-width panel of field rows. */
export function SettingsSection(props: SettingsSectionProps) {
  const { section, fields, editable, controller } = props
  const rows = fields.filter((field) => field.section === section)
  const headingId = `settings-section-${section}`
  return (
    <section aria-labelledby={headingId} className="space-y-3">
      <h3 id={headingId} className="fs-section-title">
        {SECTION_TITLES[section]}
      </h3>
      <div className="fs-panel divide-y divide-[var(--hairline)]">
        {rows.map((field) => (
          <SettingsFieldRow
            key={field.id}
            field={field}
            draft={controller.draft}
            editable={editable}
            pending={controller.pending}
            generation={controller.generation}
            onChange={controller.setValue}
            onInherit={controller.inherit}
            onValidity={controller.setValidity}
          />
        ))}
      </div>
    </section>
  )
}
