import { useCallback, useEffect, useRef, useState } from "react"
import { applySettingsCopy, getProjectSettings, previewSettingsCopy } from "@/domains/settings"
import type { CopyBinding, CopyMode, CopyPlan, CopyResult } from "@/domains/settings"
import { isConflict, isForbidden } from "@/shared/api/conflict"

export const COPY_CONFLICT = "Settings changed since the preview. Preview again"
export const COPY_PREVIEW_FAILED = "The preview could not be loaded"
export const COPY_APPLY_FAILED = "The settings could not be copied"
export const COPY_FORBIDDEN = "You do not have permission to copy these settings"

/** "Copied 1 setting." / "Copied 3 settings." */
export function copiedNotice(count: number): string {
  return `Copied ${count} ${count === 1 ? "setting" : "settings"}.`
}

export interface CopySettingsController {
  sourceId: string
  setSourceId: (id: string) => void
  mode: CopyMode
  setMode: (mode: CopyMode) => void
  /** Binding choices of the last preview; kept when only the selection changes. */
  choices: readonly CopyBinding[]
  selected: ReadonlySet<string>
  toggleBinding: (bindingId: string, on: boolean) => void
  /** The current preview; a change to source or mode clears it. */
  preview: CopyPlan | null
  pending: boolean
  error: string | null
  runPreview: () => Promise<void>
  apply: () => Promise<CopyResult | null>
}

/** Read both revisions, then preview with them; nothing is written. */
async function loadPreview(options: {
  targetProjectId: string
  sourceId: string
  mode: CopyMode
  versions: Record<string, number>
  signal: AbortSignal
}): Promise<CopyPlan> {
  const { targetProjectId, sourceId, mode, versions, signal } = options
  const [source, target] = await Promise.all([
    getProjectSettings(sourceId, signal),
    getProjectSettings(targetProjectId, signal),
  ])
  return previewSettingsCopy(
    targetProjectId,
    {
      sourceProjectId: sourceId,
      mode,
      sourceRevision: source.projectRevision,
      targetRevision: target.projectRevision,
      systemRevision: target.systemRevision,
      bindingVersions: versions,
    },
    signal
  )
}

function failure(error: unknown, fallback: string): string {
  if (isConflict(error)) return COPY_CONFLICT
  return isForbidden(error) ? COPY_FORBIDDEN : fallback
}

/**
 * Revision-bound copy into one target project.
 *
 * Preview reads the source and target revisions and sends them with the
 * selected binding versions; nothing is written. Apply echoes exactly the
 * preview's three revisions and the versions of the currently selected
 * eligible bindings; a binding toggle keeps the preview because the field
 * plan does not depend on it and apply checks each selected version.
 * Unmount (dialog close, project switch) aborts a running preview.
 */
export function useCopySettings(targetProjectId: string): CopySettingsController {
  const [sourceId, setSource] = useState("")
  const [mode, setModeState] = useState<CopyMode>("overrides_only")
  const [choices, setChoices] = useState<readonly CopyBinding[]>([])
  const [selected, setSelected] = useState<ReadonlySet<string>>(new Set())
  const [preview, setPreview] = useState<CopyPlan | null>(null)
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const controllerRef = useRef<AbortController | null>(null)

  useEffect(() => () => controllerRef.current?.abort(), [])

  const resetChoices = () => {
    controllerRef.current?.abort()
    setPending(false)
    setPreview(null)
    setChoices([])
    setSelected(new Set())
    setError(null)
  }

  const setSourceId = (id: string) => {
    resetChoices()
    setSource(id)
  }

  const setMode = (next: CopyMode) => {
    resetChoices()
    setModeState(next)
  }

  const toggleBinding = (bindingId: string, on: boolean) => {
    setSelected((previous) => {
      const next = new Set(previous)
      if (on) next.add(bindingId)
      else next.delete(bindingId)
      return next
    })
  }

  const runPreview = async () => {
    if (sourceId === "") return
    controllerRef.current?.abort()
    const controller = new AbortController()
    controllerRef.current = controller
    setPending(true)
    setError(null)
    try {
      const plan = await loadPreview({
        targetProjectId,
        sourceId,
        mode,
        versions: bindingVersions(choices, selected),
        signal: controller.signal,
      })
      if (controller.signal.aborted) return
      setPreview(plan)
      setChoices(plan.bindings)
      setSelected(new Set(plan.bindings.filter((b) => b.selected && b.eligible).map((b) => b.bindingId)))
    } catch (caught) {
      if (!controller.signal.aborted) setError(failure(caught, COPY_PREVIEW_FAILED))
    } finally {
      if (!controller.signal.aborted) setPending(false)
    }
  }

  const apply = useCallback(async (): Promise<CopyResult | null> => {
    if (preview === null) return null
    setPending(true)
    setError(null)
    try {
      return await applySettingsCopy(targetProjectId, {
        sourceProjectId: preview.sourceProjectId || sourceId,
        mode: preview.mode,
        sourceRevision: preview.sourceRevision,
        targetRevision: preview.targetRevision,
        systemRevision: preview.systemRevision,
        bindingVersions: bindingVersions(preview.bindings.filter((b) => b.eligible), selected),
      })
    } catch (caught) {
      if (isConflict(caught)) setPreview(null)
      setError(failure(caught, COPY_APPLY_FAILED))
      return null
    } finally {
      setPending(false)
    }
  }, [preview, selected, sourceId, targetProjectId])

  return {
    sourceId,
    setSourceId,
    mode,
    setMode,
    choices,
    selected,
    toggleBinding,
    preview,
    pending,
    error,
    runPreview,
    apply,
  }
}

/** Versions of the selected bindings, keyed by binding id. */
export function bindingVersions(
  bindings: readonly CopyBinding[],
  selected: ReadonlySet<string>
): Record<string, number> {
  return Object.fromEntries(
    bindings.filter((binding) => selected.has(binding.bindingId)).map((b) => [b.bindingId, b.version])
  )
}
