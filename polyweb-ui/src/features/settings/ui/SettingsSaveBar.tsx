import { Button } from "@/shared/ui/button"

interface SettingsSaveBarProps {
  changeCount: number
  /** Inputs that hold a value the draft cannot take. */
  invalidCount: number
  pending: boolean
  onDiscard: () => void
  onSave: () => void
}

/** "1 unsaved change" / "3 unsaved changes" / "1 field to fix" */
function statusText(changeCount: number, invalidCount: number): string {
  if (invalidCount > 0) return `${invalidCount} ${invalidCount === 1 ? "field" : "fields"} to fix`
  return `${changeCount} unsaved ${changeCount === 1 ? "change" : "changes"}`
}

/**
 * The one save point of the settings page. It is fixed to the bottom right of
 * the viewport, so it stays visible however far the page scrolls, and shows
 * only while the draft holds a change or an input holds an invalid value.
 * Save stays enabled; with an invalid input it explains what to fix.
 */
export function SettingsSaveBar({ changeCount, invalidCount, pending, onDiscard, onSave }: SettingsSaveBarProps) {
  if (changeCount === 0 && invalidCount === 0) return null
  return (
    <div
      role="region"
      aria-label="Unsaved changes"
      className="fixed right-8 bottom-6 z-30 flex items-center gap-4 rounded-lg border border-[var(--border-subtle)] bg-[var(--raised)] py-2 pr-2 pl-4 shadow-lg"
    >
      <span className="text-[13px] text-[var(--text)] tnum">{statusText(changeCount, invalidCount)}</span>
      <div className="flex items-center gap-2">
        <Button size="form" variant="outline" disabled={pending} onClick={onDiscard}>
          Discard
        </Button>
        <Button size="form" disabled={pending} onClick={onSave}>
          Save changes
        </Button>
      </div>
    </div>
  )
}
