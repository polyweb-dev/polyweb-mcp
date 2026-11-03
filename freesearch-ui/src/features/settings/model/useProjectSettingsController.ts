import { useCallback, useState } from "react"
import { getProjectSettings, updateProjectSettings } from "@/domains/settings"
import type { ProjectSettings, SettingsField, SettingsValue } from "@/domains/settings"
import { isConflict, isForbidden } from "@/shared/api/conflict"
import { useScopedResource } from "@/shared/lib/useScopedResource"
import type { ScopedResourceState } from "@/shared/lib/useScopedResource"
import { sectionChanges, withoutSection } from "./settingsDraft"
import type { SettingsDraft } from "./settingsDraft"

export const SETTINGS_SAVED = "Settings saved."
export const SETTINGS_CONFLICT = "Settings changed since you opened them."
export const SETTINGS_SAVE_FAILED = "The settings could not be saved."
export const SETTINGS_FORBIDDEN = "You do not have permission to change these settings."

export interface ProjectSettingsController {
  settings: ScopedResourceState<ProjectSettings>
  draft: SettingsDraft
  setValue: (field: SettingsField, value: SettingsValue) => void
  inherit: (field: SettingsField) => void
  hasChanges: (section: string) => boolean
  save: (section: string) => Promise<void>
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
 * Save sends only the changed fields of one section at the loaded
 * `project_revision`; Inherit marks one field `null`. A 409 keeps the draft
 * and asks for a reload. The read is bound to `accountId:projectId`.
 */
export function useProjectSettingsController(options: {
  accountId: string
  projectId: string
}): ProjectSettingsController {
  const { accountId, projectId } = options
  const scopeKey = `${accountId}:${projectId}:settings`
  const resource = useScopedResource({
    scopeKey,
    load: (signal) => getProjectSettings(projectId, signal),
  })
  const [saved, setSaved] = useState<Saved | null>(null)
  const [draft, setDraft] = useState<SettingsDraft>({})
  const [pending, setPending] = useState(false)
  const [message, setMessage] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [conflict, setConflict] = useState(false)
  const reloadResource = resource.reload

  const settings: ScopedResourceState<ProjectSettings> =
    saved !== null && saved.scopeKey === scopeKey ? { status: "ready", data: saved.data } : resource
  const current = settings.status === "ready" ? settings.data : null

  const setValue = useCallback((field: SettingsField, value: SettingsValue) => {
    setNotice(null)
    setDraft((previous) => ({ ...previous, [field.id]: value }))
  }, [])

  const inherit = useCallback((field: SettingsField) => setValue(field, null), [setValue])

  const hasChanges = (section: string) =>
    current !== null && Object.keys(sectionChanges(draft, current.fields, section)).length > 0

  const save = async (section: string) => {
    if (current === null) return
    const changes = sectionChanges(draft, current.fields, section)
    if (Object.keys(changes).length === 0) return
    setPending(true)
    setMessage(null)
    setNotice(null)
    try {
      const next = await updateProjectSettings(projectId, changes, current.projectRevision)
      setSaved({ scopeKey, data: next })
      setDraft((previous) => withoutSection(previous, current.fields, section))
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
    setDraft({})
    setConflict(false)
    setMessage(null)
    setNotice(null)
    void reloadResource()
  }, [reloadResource])

  const replace = useCallback(
    (data: ProjectSettings, text: string) => {
      setSaved({ scopeKey, data })
      setDraft({})
      setConflict(false)
      setMessage(null)
      setNotice(text)
    },
    [scopeKey]
  )

  return {
    settings,
    draft,
    setValue,
    inherit,
    hasChanges,
    save,
    pending,
    message,
    notice,
    conflict,
    reload,
    replace,
  }
}
