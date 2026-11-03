import type { Project } from "@/domains/projects"
import type { ProjectSettings } from "@/domains/settings"
import { Button } from "@/shared/ui/button"
import { copiedNotice, useCopySettings } from "../model/useCopySettings"
import { CopyBindingChoices } from "./CopyBindingChoices"
import { CopyPreviewView } from "./CopyPreviewView"

const FIELD_CLASS =
  "w-full rounded border border-[var(--border-subtle)] bg-[var(--surface)] px-2 py-1.5 text-[13px] text-[var(--text)] outline-none focus-visible:border-[var(--signal)] disabled:opacity-60"

/** Target project of a copy and the callback that shows its new settings. */
export interface CopyTarget {
  projectId: string
  onApplied: (settings: ProjectSettings, notice: string) => void
}

interface CopySettingsFormProps {
  target: CopyTarget
  sources: readonly Project[]
  onClose: () => void
}

/**
 * Body of the Copy settings dialog: source, mode, Preview, then Apply for
 * exactly that preview. Mounted only while the dialog is open.
 */
export function CopySettingsForm({ target, sources, onClose }: CopySettingsFormProps) {
  const copy = useCopySettings(target.projectId)
  const { preview } = copy

  const apply = async () => {
    const result = await copy.apply()
    if (result === null) return
    target.onApplied(result.settings, copiedNotice(result.plan.fields.length))
    onClose()
  }

  return (
    <div className="space-y-4 text-[13px]">
      {copy.error !== null && <p role="alert" className="text-[var(--status-danger)]">{copy.error}</p>}
      <div>
        <label htmlFor="copy-source" className="mb-1 block text-[12px] text-[var(--muted)]">
          Source project
        </label>
        <select id="copy-source" value={copy.sourceId} disabled={copy.pending} onChange={(event) => copy.setSourceId(event.target.value)} className={FIELD_CLASS}>
          <option value="">Choose a project</option>
          {sources.map((project) => (
            <option key={project.id} value={project.id}>{project.name}</option>
          ))}
        </select>
      </div>
      <fieldset className="space-y-1">
        <legend className="mb-1 text-[12px] text-[var(--muted)]">Mode</legend>
        <label className="mr-4 inline-flex items-center gap-2">
          <input type="radio" name="copy-mode" checked={copy.mode === "overrides_only"} onChange={() => copy.setMode("overrides_only")} />
          Overrides only
        </label>
        <label className="inline-flex items-center gap-2">
          <input type="radio" name="copy-mode" checked={copy.mode === "effective_snapshot"} onChange={() => copy.setMode("effective_snapshot")} />
          Effective snapshot
        </label>
        <p className="text-[12px] text-[var(--muted)]">Pins current values and stops inheritance.</p>
      </fieldset>
      <Button type="button" variant="outline" disabled={copy.pending || copy.sourceId === ""} onClick={() => void copy.runPreview()}>
        Preview
      </Button>
      {preview !== null && (
        <div data-testid="copy-preview" className="space-y-3">
          <CopyPreviewView plan={preview} />
          <CopyBindingChoices bindings={copy.choices} selected={copy.selected} disabled={copy.pending} onToggle={copy.toggleBinding} />
        </div>
      )}
      {preview === null && copy.choices.length > 0 && (
        <div className="space-y-2">
          <CopyBindingChoices bindings={copy.choices} selected={copy.selected} disabled={copy.pending} onToggle={copy.toggleBinding} />
          <p className="text-[12px] text-[var(--muted)]">Preview again to include your binding choice.</p>
        </div>
      )}
      <div className="flex justify-end gap-2">
        <Button type="button" variant="outline" onClick={onClose}>Cancel</Button>
        <Button type="button" disabled={copy.pending || preview === null} onClick={() => void apply()}>
          Apply copy
        </Button>
      </div>
    </div>
  )
}
