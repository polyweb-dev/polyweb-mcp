import { useCallback, useState } from "react"
import { getProjectSettings, updateProjectSettings } from "@/domains/settings"
import type { ProjectSettings, SettingsField, SettingsValue } from "@/domains/settings"
import { isConflict, isForbidden } from "@/shared/api/conflict"
import { useScopedResource } from "@/shared/lib/useScopedResource"
import type { ScopedResourceState } from "@/shared/lib/useScopedResource"
import { draftChanges } from "./settingsDraft"
import type { SettingsDraft } from "./settingsDraft"
import { useFieldValidity } from "./useFieldValidity"

export const SETTINGS_SAVED = "Settings saved"
export const SETTINGS_CONFLICT = "Settings changed since you opened them."
export const SETTINGS_SAVE_FAILED = "The settings could not be saved."
export const SETTINGS_FORBIDDEN = "You do not have permission to change these settings."
export const SETTINGS_INVALID = "Fix the highlighted fields before saving"

export interface ProjectSettingsController {
  settings: ScopedResourceState<ProjectSettings>
  draft: SettingsDraft
  setValue: (field: SettingsField, value: SettingsValue) => void
  inherit: (field: SettingsField) => void
  /** Report whether one field's input holds a value the draft can take. */
  setValidity: (fieldId: string, valid: boolean) => void
  /** Number of fields whose draft differs from the stored override. */
  changeCount: number
  /** Number of inputs that hold an invalid value. */
  invalidCount: number
  /** Send every changed field in one write; refuses while an input is invalid. */
  save: () => Promise<void>
  /** Drop the draft; controls restart from the stored values. */
  discard: () => void
  /** Bumped by a save, a discard or a reload so controls restart from the value. */
  generation: number
  pending: boolean
  message: string | null
  notice: string | null
  /** A save met a stale revision; the page offers "Reload settings". */
  conflict: boolean
  reload: () => void
  /** Show settings another flow (copy) just wrote. */
  replace: (settings: ProjectSettings, notice: string) => void
}

interface Saved {
  scopeKey: string
  data: ProjectSettings
}

/**
 * Settings controller of one project.
 *
 * Save sends only the changed fields of the whole page in one write at the
 * loaded `project_revision`; Inherit marks one field `null`. While any input
 * is invalid, Save shows a message instead of writing. A 409 keeps the draft
 * and asks for a reload. The read is bound to `accountId:projectId`.
 */
export function useProjectSettingsController(options: {
  accountId: string
  projectId: string
}): ProjectSettingsController {
  const { accountId, projectId } = options
  const scopeKey = `${accountId}:${projectId}:settings`
  const resource = useScopedResource({ scopeKey, load: (signal) => getProjectSettings(projectId, signal) })
  const validity = useFieldValidity()
  const [saved, setSaved] = useState<Saved | null>(null)
  const [draft, setDraft] = useState<SettingsDraft>({})
  const [generation, setGeneration] = useState(0)
  const [pending, setPending] = useState(false)
  const [message, setMessage] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [conflict, setConflict] = useState(false)
  const { reload: reloadResource } = resource
  const { clear: clearValidity } = validity

  const settings: ScopedResourceState<ProjectSettings> =
    saved !== null && saved.scopeKey === scopeKey ? { status: "ready", data: saved.data } : resource
  const current = settings.status === "ready" ? settings.data : null
  const changes = current === null ? {} : draftChanges(draft, current.fields)
  const changeCount = Object.keys(changes).length

  /** Drop the draft and restart every control from the stored value. */
  const restart = useCallback(() => {
    setDraft({})
    setGeneration((value) => value + 1)
    setMessage(null)
    clearValidity()
  }, [clearValidity])

  const setValue = useCallback((field: SettingsField, value: SettingsValue) => {
    setNotice(null)
    setDraft((previous) => ({ ...previous, [field.id]: value }))
  }, [])

  const inherit = useCallback((field: SettingsField) => setValue(field, null), [setValue])

  const save = async () => {
    if (validity.invalid.size > 0) {
      setMessage(SETTINGS_INVALID)
      return
    }
    if (current === null || changeCount === 0) return
    setPending(true)
    setMessage(null)
    setNotice(null)
    try {
      setSaved({ scopeKey, data: await updateProjectSettings(projectId, changes, current.projectRevision) })
      restart()
      setNotice(SETTINGS_SAVED)
    } catch (error) {
      setConflict(isConflict(error))
      if (!isConflict(error)) setMessage(isForbidden(error) ? SETTINGS_FORBIDDEN : SETTINGS_SAVE_FAILED)
    } finally {
      setPending(false)
    }
  }

  const reload = useCallback(() => {
    setSaved(null)
    restart()
    setConflict(false)
    setNotice(null)
    void reloadResource()
  }, [reloadResource, restart])

  const replace = useCallback(
    (data: ProjectSettings, text: string) => {
      setSaved({ scopeKey, data })
      restart()
      setConflict(false)
      setNotice(text)
    },
    [scopeKey, restart]
  )

  return {
    settings,
    draft,
    setValue,
    inherit,
    setValidity: validity.setValidity,
    changeCount,
    invalidCount: validity.invalid.size,
    save,
    discard: restart,
    generation,
    pending,
    message,
    notice,
    conflict,
    reload,
    replace,
  }
}
