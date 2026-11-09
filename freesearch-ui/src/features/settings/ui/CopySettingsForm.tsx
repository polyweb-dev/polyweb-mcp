import { useState } from "react"
import type { Project } from "@/domains/projects"
import type { CopyMode, ProjectSettings } from "@/domains/settings"
import { Button } from "@/shared/ui/button"
import { Field } from "@/shared/ui/Field"
import { fieldDescribedBy } from "@/shared/ui/fieldIds"
import { FormActions } from "@/shared/ui/FormActions"
import { SegmentedControl } from "@/shared/ui/SegmentedControl"
import { Select } from "@/shared/ui/select"
import { copiedNotice, useCopySettings } from "../model/useCopySettings"
import { CopyBindingChoices } from "./CopyBindingChoices"
import { CopyPreviewView } from "./CopyPreviewView"

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

const MODE_LABELS: Record<CopyMode, string> = {
  overrides_only: "Changed values",
  effective_snapshot: "All current values",
}

const MODE_HINTS: Record<CopyMode, string> = {
  overrides_only: "Copies only the values the other project changed from the system defaults",
  effective_snapshot: "Copies every current value; this project stops following the system defaults",
}

const SOURCE_MISSING = "Choose a project to copy from"

function modeOfLabel(label: string): CopyMode {
  return label === MODE_LABELS.effective_snapshot ? "effective_snapshot" : "overrides_only"
}

/**
 * Body of the Copy settings dialog: the source project, then what to copy
 * (stacked), then the preview. One primary button moves from "Preview
 * changes" to "Apply changes"; it stays enabled and, with no source chosen,
 * says so under the source field. Mounted only while the dialog is open.
 */
export function CopySettingsForm({ target, sources, onClose }: CopySettingsFormProps) {
  const copy = useCopySettings(target.projectId)
  const { preview } = copy
  const [sourceMissing, setSourceMissing] = useState(false)
  const noSources = sources.length === 0

  const apply = async () => {
    const result = await copy.apply()
    if (result === null) return
    target.onApplied(result.settings, copiedNotice(result.plan.fields.length))
    onClose()
  }

  const chooseMode = (label: string) => {
    const next = modeOfLabel(label)
    if (next !== copy.mode) copy.setMode(next)
  }

  const chooseSource = (id: string) => {
    setSourceMissing(false)
    copy.setSourceId(id)
  }

  const startPreview = () => {
    if (copy.sourceId === "") {
      setSourceMissing(true)
      return
    }
    void copy.runPreview()
  }

  return (
    <div className="text-[13px]">
      <div className="space-y-5">
        <Field
          id="copy-source"
          label="Source project"
          hint={noSources ? "No other project to copy from" : undefined}
          error={sourceMissing ? SOURCE_MISSING : null}
        >
          <Select
            id="copy-source"
            value={copy.sourceId}
            placeholder="Choose a project"
            options={sources.map((project) => ({ value: project.id, label: project.name }))}
            disabled={copy.pending}
            invalid={sourceMissing}
            ariaDescribedBy={fieldDescribedBy("copy-source", noSources, sourceMissing)}
            onValueChange={chooseSource}
          />
        </Field>
        <div className="min-w-0">
          <p className="fs-label">Copy</p>
          <SegmentedControl
            ariaLabel="Copy mode"
            options={[MODE_LABELS.overrides_only, MODE_LABELS.effective_snapshot]}
            value={MODE_LABELS[copy.mode]}
            disabled={copy.pending}
            onChange={chooseMode}
          />
          <p className="fs-hint">{MODE_HINTS[copy.mode]}</p>
        </div>
        {preview !== null && (
          <div data-testid="copy-preview" className="space-y-4">
            <CopyPreviewView plan={preview} />
            <CopyBindingChoices bindings={copy.choices} selected={copy.selected} disabled={copy.pending} onToggle={copy.toggleBinding} />
          </div>
        )}
      </div>
      <FormActions start={copy.error !== null && <span role="alert" className="text-[var(--status-danger)]">{copy.error}</span>}>
        <Button type="button" size="form" variant="outline" onClick={onClose}>Cancel</Button>
        {preview === null ? (
          <Button type="button" size="form" disabled={copy.pending} onClick={startPreview}>
            Preview changes
          </Button>
        ) : (
          <Button type="button" size="form" disabled={copy.pending} onClick={() => void apply()}>
            Apply changes
          </Button>
        )}
      </FormActions>
    </div>
  )
}
