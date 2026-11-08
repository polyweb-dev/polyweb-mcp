import { fieldLabel } from "@/domains/settings"
import type { CopyPlan } from "@/domains/settings"
import { Tag } from "@/shared/ui/Tag"
import { valueText } from "../model/settingsFormat"

function rejectedLabel(fieldId: string): string {
  return fieldId.startsWith("binding:") ? "Route" : fieldLabel(fieldId)
}

/** The settings the copy writes and the ones it refuses; a preview writes nothing. */
export function CopyPreviewView({ plan }: { plan: CopyPlan }) {
  return (
    <div className="space-y-3">
      <h3 className="fs-section-title">Review the changes</h3>
      <div className="fs-panel overflow-x-auto">
        <table aria-label="Settings to copy" className="fs-table">
          <thead>
            <tr>
              <th scope="col">Setting</th>
              <th scope="col">New value</th>
              <th scope="col" className="w-28">Change</th>
            </tr>
          </thead>
          <tbody>
            {plan.fields.length === 0 && (
              <tr>
                <td colSpan={3} className="fs-cell-empty">Nothing to copy</td>
              </tr>
            )}
            {plan.fields.map((field) => (
              <tr key={field.fieldId}>
                <td className="fs-cell-strong">{fieldLabel(field.fieldId)}</td>
                <td className="tnum">{valueText(field.fieldId, field.value)}</td>
                <td>{field.changed ? <Tag tone="accent">Changes</Tag> : <span className="text-[var(--muted)]">No change</span>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {plan.rejected.length > 0 && (
        <div>
          <p className="fs-label">Not copied</p>
          <ul className="space-y-1 text-[13px] text-[var(--text)]">
            {plan.rejected.map((rejection) => (
              <li key={rejection.fieldId}>
                <span className="font-medium text-[var(--text-strong)]">{rejectedLabel(rejection.fieldId)}</span>
                <span className="text-[var(--muted)]"> · {rejection.reason}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
