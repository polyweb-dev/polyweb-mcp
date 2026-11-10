import { useState } from "react"
import { BASE_ACCESS, DEVELOPER_BITS, memberPermissionSummary, PERMISSION_GROUPS, PERMISSION_PRESETS, updateProjectMember } from "@/domains/projects"
import type { ProjectMember } from "@/domains/projects"
import { ApiError } from "@/shared/api/http"
import { Button } from "@/shared/ui/button"
import { FormActions } from "@/shared/ui/FormActions"
import { Modal } from "@/shared/ui/Modal"
import { SegmentedControl } from "@/shared/ui/SegmentedControl"
import { Switch } from "@/shared/ui/Switch"
import { memberActionLabel } from "../model/memberIdentity"

interface Props {
  projectId: string
  member: ProjectMember
  onClose: () => void
  onSaved: () => void
}

export function MemberPermissionsDialog({ projectId, member, onClose, onSaved }: Props) {
  const admin = member.role === "admin"
  const initial = admin ? DEVELOPER_BITS : member.permissions & DEVELOPER_BITS
  const [bits, setBits] = useState(initial)
  const [error, setError] = useState<string | null>(null)
  const [pending, setPending] = useState(false)
  const preset = Object.entries(PERMISSION_PRESETS).find(([, value]) => value === bits)?.[0] ?? ""
  const save = async () => {
    if (pending) return
    if (bits === initial) {
      onClose()
      return
    }
    setPending(true)
    setError(null)
    try {
      await updateProjectMember(projectId, member.user_id, { permissions: bits })
      onSaved()
      onClose()
    } catch (failure) {
      setError(failure instanceof ApiError && failure.status === 404
        ? "This action is not available yet" : "The permissions did not save. Try again")
    } finally {
      setPending(false)
    }
  }
  return (
    <Modal isOpen onClose={onClose} title={`Permissions for ${memberActionLabel(member)}`} subtitle="Turn on only what this person needs" maxWidth="4xl">
      <div data-testid="permissions-scroll" className="space-y-2 [--control-on:color-mix(in_srgb,var(--text-strong)_55%,var(--elevated))]">
        <div className="flex items-center gap-3">
          <span>Preset</span>
          <SegmentedControl ariaLabel="Preset" options={Object.keys(PERMISSION_PRESETS)} value={preset} disabled={admin || pending}
            onChange={(value) => setBits(PERMISSION_PRESETS[value as keyof typeof PERMISSION_PRESETS])} />
          {!preset && <span className="text-[var(--muted)]">Custom permissions</span>}
        </div>
        <div className="grid min-h-8 grid-cols-[180px_minmax(0,1fr)_auto] items-center gap-4 border-t border-[var(--border-subtle)] py-1">
          <span>{BASE_ACCESS.label}</span><span className="text-[var(--muted)]">{BASE_ACCESS.description}</span>
          <Switch ariaLabel={BASE_ACCESS.label} checked disabled onChange={() => {}} />
        </div>
        {PERMISSION_GROUPS.map((group) => (
          <section key={group.name} aria-label={group.name}>
            <h3 className="mb-1 text-[12px] text-[var(--muted)]">{group.name}</h3>
            {group.items.map((item) => (
              <div key={item.bit} className="grid min-h-8 grid-cols-[180px_minmax(0,1fr)_auto] items-center gap-4 border-t border-[var(--border-subtle)] py-1">
                <span>{item.label}</span><span className="text-[var(--muted)]">{item.description}</span>
                <Switch ariaLabel={item.label} checked={(bits & item.bit) !== 0} disabled={admin || pending}
                  onChange={(checked) => setBits(checked ? bits | item.bit : bits & ~item.bit)} />
              </div>
            ))}
          </section>
        ))}
        <p className="text-[var(--muted)]">Project admins also manage members and provider capacity. They can archive the project</p>
      </div>
      {error && <p role="alert" className="shrink-0 pt-3 text-[var(--status-danger)]">{error}</p>}
      <FormActions
        start={<p role="status">{memberPermissionSummary(bits)}</p>}>
        <Button variant="outline" size="form" onClick={onClose}>Cancel</Button>
        {!admin && <Button size="form" pending={pending} pendingLabel="Saving…" onClick={() => void save()}>Save permissions</Button>}
      </FormActions>
    </Modal>
  )
}
