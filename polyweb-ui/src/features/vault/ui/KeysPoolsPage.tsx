import { useCallback, useContext, useState } from "react"
import { useAuth } from "@/domains/auth"
import { providerTypeName } from "@/domains/providers"
import { deleteKeyPool, deleteVaultKey, disconnectVaultOAuth, getVaultOAuth, listKeyPools, listVaultKeys, listVaultProjects, unassignKeyPool } from "@/domains/vault"
import type { KeyPool, VaultKeyDeleteResult, VaultProject } from "@/domains/vault"
import { ApiError } from "@/shared/api/http"
import { useScopedResource } from "@/shared/lib/useScopedResource"
import { NotificationsContext } from "@/shared/notifications/context"
import { Button } from "@/shared/ui/button"
import { ConfirmDialog } from "@/shared/ui/ConfirmDialog"
import { EmptyState } from "@/shared/ui/EmptyState"
import { PageHeader } from "@/shared/ui/PageHeader"
import { AddCapacityDialog } from "./AddCapacityDialog"
import { BulkPoolsDialog } from "./BulkPoolsDialog"
import { KeyDialog } from "./KeyDialog"
import { KeylessDefaultsDialog } from "./KeylessDefaultsDialog"
import { KeysTable } from "./KeysTable"
import { PoolProjectDialog } from "./PoolProjectDialog"
import { VaultOAuthDialog } from "./VaultOAuthDialog"
import type { KeyAction, PoolAction, VaultRow } from "./vaultTableTypes"

type Dialog =
  | { type: "add" }
  | { type: "bulk" }
  | { type: "keyless-defaults" }
  | { type: KeyAction; row: VaultRow }
  | { type: PoolAction; row: VaultRow; pool: KeyPool }

async function loadVault(signal: AbortSignal): Promise<{ rows: VaultRow[]; projects: VaultProject[] }> {
  const [keys, projects] = await Promise.all([listVaultKeys(signal), listVaultProjects(signal)])
  const rows = await Promise.all(keys.map(async (key) => {
    const [pools, oauth] = await Promise.all([
      listKeyPools(key.id, signal),
      key.auth_mode === "oauth" ? getVaultOAuth(key.id, signal).then((value) => value.status).catch(() => null) : Promise.resolve(null),
    ])
    return { key, pools, oauth }
  }))
  return { rows, projects }
}

export function KeysPoolsPage() {
  const { account } = useAuth()
  const resource = useScopedResource({ scopeKey: `vault:${account?.id ?? ""}`, load: loadVault })
  const [dialog, setDialog] = useState<Dialog | null>(null)
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const notifications = useContext(NotificationsContext)
  const reload = resource.reload
  const close = () => { setDialog(null); setError(null) }
  const saved = (notice?: string) => {
    const message = notice ?? (dialog === null ? null : successMessage(dialog))
    if (message !== null && message !== undefined) notifications?.showToast(message, "success")
    close()
    void reload()
  }
  const connected = useCallback(() => { void reload() }, [reload])
  async function confirm() {
    if (!dialog || !("row" in dialog)) return
    setPending(true)
    setError(null)
    try {
      if (dialog.type === "delete" && "pool" in dialog) await deleteKeyPool(dialog.pool.id)
      else if (dialog.type === "delete") {
        const result = await deleteVaultKey(dialog.row.key.id)
        saved(deletedKeyMessage(result, dialog.row.pools, projects))
        return
      }
      else if (dialog.type === "unassign" && "pool" in dialog) await unassignKeyPool(dialog.pool.id)
      else if (dialog.type === "disconnect") await disconnectVaultOAuth(dialog.row.key.id)
      saved()
    } catch {
      setError("The change did not save. Try again")
    } finally {
      setPending(false)
    }
  }
  const projects = resource.status === "ready" ? resource.data.projects : []
  const rows = resource.status === "ready" ? resource.data.rows : []
  return (
    <section className="flex flex-1 flex-col">
      <PageHeader
        title="Keys and pools"
        description="Provider keys you own and the pools that give projects access"
        actions={<><Button size="form" variant="outline" onClick={() => setDialog({ type: "keyless-defaults" })}>Create keyless defaults</Button><Button size="form" variant="outline" onClick={() => setDialog({ type: "bulk" })}>Bulk create pools</Button><Button size="form" onClick={() => setDialog({ type: "add" })}>Add key</Button></>}
      />
      <div>
        {resource.status === "loading" && <p role="status">Wait while the keys load</p>}
        {resource.status === "error" && (resource.error instanceof ApiError && resource.error.status === 404
          ? <EmptyState title="Keys and pools are not available yet" description="Try again later" />
          : <div><p role="alert">The keys did not load. Try again.</p><Button size="form" variant="outline" onClick={() => void resource.reload()}>Retry</Button></div>)}
        {resource.status === "ready" && (resource.data.rows.length === 0
          ? <EmptyState title="No keys yet" description="Add a provider key, then create a pool to let a project use it" action={<Button size="form" onClick={() => setDialog({ type: "add" })}>Add key</Button>} />
          : <KeysTable rows={resource.data.rows} projects={projects}
              onKey={(type, row) => setDialog({ type, row })}
              onPool={(type, row, pool) => setDialog({ type, row, pool })} />)}
      </div>
      {renderDialogs({ dialog, rows, projects, close, saved, connected, pending, error, confirm })}
    </section>
  )
}

function deletedKeyMessage(result: VaultKeyDeleteResult, pools: KeyPool[], projects: VaultProject[]): string {
  if (result.deleted_pools.length === 0) return "Key deleted"
  const names = result.deleted_pools.map(({ id, project_id }) => {
    const pool = pools.find((entry) => entry.id === id)?.label ?? id
    const project = project_id ? projects.find((entry) => entry.id === project_id)?.name ?? project_id : "Unassigned"
    return `${pool} (${project})`
  })
  return `Key deleted. Deleted pools: ${names.join(", ")}`
}

interface DialogProps {
  dialog: Dialog | null
  rows: VaultRow[]
  projects: VaultProject[]
  close: () => void
  saved: () => void
  connected: () => void
  pending: boolean
  error: string | null
  confirm: () => Promise<void>
}

function renderDialogs(props: DialogProps) {
  return <>{renderEditDialogs(props)}{renderActionDialogs(props)}</>
}

function renderEditDialogs({ dialog, rows, projects, close, saved }: DialogProps) {
  if (!dialog) return null
  return <>
    {dialog.type === "add" && <KeyDialog mode="add" onClose={close} onSaved={saved} />}
    {dialog.type === "bulk" && <BulkPoolsDialog rows={rows} projects={projects} onClose={close} onSaved={saved} />}
    {dialog.type === "keyless-defaults" && <KeylessDefaultsDialog rows={rows} projects={projects} onClose={close} onSaved={saved} />}
    {"row" in dialog && !("pool" in dialog) && (dialog.type === "settings" || dialog.type === "rotate") && <KeyDialog mode={dialog.type} item={dialog.row.key} onClose={close} onSaved={saved} />}
    {dialog.type === "create" && <AddCapacityDialog item={dialog.row.key} projects={projects} onClose={close} onSaved={saved} />}
    {"pool" in dialog && dialog.type === "edit" && <AddCapacityDialog item={dialog.row.key} pool={dialog.pool} projects={projects} onClose={close} onSaved={saved} />}
  </>
}

function renderActionDialogs({ dialog, projects, close, saved, connected, pending, error, confirm }: DialogProps) {
  return <>
    {dialog && "pool" in dialog && (dialog.type === "copy" || dialog.type === "assign") && <PoolProjectDialog mode={dialog.type} item={dialog.row.key} pool={dialog.pool} projects={projects} onClose={close} onSaved={saved} />}
    {dialog?.type === "connect" && <VaultOAuthDialog keyId={dialog.row.key.id} onClose={close} onConnected={connected} />}
    {dialog && "row" in dialog && (dialog.type === "delete" || dialog.type === "unassign" || dialog.type === "disconnect") && <ConfirmDialog
      open title={confirmTitle(dialog, projects)} message={confirmMessage(dialog, projects)} confirmLabel={confirmLabel(dialog)} pending={pending} error={error} onClose={close} onConfirm={() => void confirm()} />}
  </>
}

function successMessage(dialog: Dialog): string | null {
  const messages: Record<string, string> = {
    add: "Key saved",
    bulk: "Pools created",
    "keyless-defaults": "Keyless defaults ready",
    rotate: "Key rotated",
    create: "Pool created",
    copy: "Pool copied",
    edit: "Pool updated",
    settings: "Key settings saved",
    assign: "Pool assigned",
    unassign: "Pool removed from project",
  }
  if ("pool" in dialog && dialog.type === "delete") return "Pool deleted"
  if (dialog.type === "delete") return "Key deleted"
  if (dialog.type === "disconnect") return "Key disconnected"
  return messages[dialog.type] ?? null
}

/** Dialog variants that carry a vault row; bulk and keyless-defaults do not. */
function hasRow(dialog: Dialog): dialog is Extract<Dialog, { row: VaultRow }> {
  return "row" in dialog
}

function confirmLabel(dialog: Exclude<Dialog, { type: "add" }>): string {
  if (!hasRow(dialog)) return "Confirm"
  if (dialog.type === "unassign") return "Remove from project"
  if (dialog.type === "disconnect") return "Disconnect"
  return "pool" in dialog ? "Delete pool" : "Delete key"
}

function confirmTitle(dialog: Exclude<Dialog, { type: "add" }>, projects: VaultProject[]): string {
  if (!hasRow(dialog)) return "Confirm"
  if (dialog.type === "unassign" && "pool" in dialog) return `Remove pool from ${projects.find((project) => project.id === dialog.pool.project_id)?.name ?? "project"}`
  if (dialog.type === "disconnect") return "Disconnect"
  return "pool" in dialog ? "Delete pool" : `Delete key ${dialog.row.key.label}`
}

function confirmMessage(dialog: Exclude<Dialog, { type: "add" }>, projects: VaultProject[]): string {
  if (!hasRow(dialog)) return "Confirm this change"
  if (dialog.type === "unassign") return `${providerTypeName(dialog.row.key.provider_type)} calls stop in this project. The pool stays in your vault`
  if (dialog.type === "disconnect") return "Disconnect this key"
  if ("pool" in dialog) return "Delete this pool. This cannot be undone"
  const count = dialog.row.pools.length
  if (count === 0) return "Delete this key"
  const ids = [...new Set(dialog.row.pools.flatMap((pool) => pool.project_id ? [pool.project_id] : []))]
  const names = ids.map((id) => projects.find((project) => project.id === id)?.name ?? id)
  const impact = names.length ? ` ${names.join(", ")} ${names.length === 1 ? "loses" : "lose"} access to ${providerTypeName(dialog.row.key.provider_type)}` : ""
  return `Delete this key and ${count === 1 ? "its pool" : `its ${count} pools`}${impact ? `.${impact}` : ""}`
}
