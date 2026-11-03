import { PROVENANCE_LABELS, fieldLabel, formatSettingsValue } from "@/domains/settings"
import type { CopyPlan } from "@/domains/settings"

const HEAD = "py-1.5 pr-3 font-medium"
const CELL = "py-1.5 pr-3 align-top"

function rejectedLabel(fieldId: string): string {
  return fieldId.startsWith("binding:") ? "Binding" : fieldLabel(fieldId)
}

/** Fields the copy writes and the ones it refuses; nothing is written by a preview. */
export function CopyPreviewView({ plan }: { plan: CopyPlan }) {
  return (
    <div className="space-y-3">
      <table aria-label="Fields to copy" className="w-full text-left text-[13px]">
        <thead>
          <tr className="border-b border-[var(--border-subtle)] text-[var(--muted)]">
            <th scope="col" className={HEAD}>Field</th>
            <th scope="col" className={HEAD}>Value</th>
            <th scope="col" className={HEAD}>Source provenance</th>
            <th scope="col" className={HEAD}>Change</th>
          </tr>
        </thead>
        <tbody>
          {plan.fields.length === 0 && (
            <tr>
              <td colSpan={4} className="py-2 text-[var(--muted)]">Nothing to copy.</td>
            </tr>
          )}
          {plan.fields.map((field) => (
            <tr key={field.fieldId} className="border-b border-[var(--border-subtle)]">
              <td className={CELL}>{fieldLabel(field.fieldId)}</td>
              <td className={CELL}>{formatSettingsValue(field.fieldId, field.value)}</td>
              <td className={CELL}>{PROVENANCE_LABELS[field.provenance]}</td>
              <td className={CELL}>{field.changed ? "Changes" : "No change"}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {plan.rejected.length > 0 && (
        <div>
          <h3 className="text-[13px] font-medium text-[var(--text-strong)]">Not copied</h3>
          <ul className="mt-1 space-y-0.5 text-[13px]">
            {plan.rejected.map((rejection) => (
              <li key={rejection.fieldId}>
                {rejectedLabel(rejection.fieldId)}: {rejection.reason}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
