import { useState } from "react"
import { getProviderOwner, hasPermission, listProjectPools, detachProjectPool, PROJECT_PERMISSIONS, SYSTEM_PERMISSIONS, useProjectScope, useProjectsOptional } from "@/domains/projects"
import type { ProjectAccess, ProjectPool, ProviderOwner } from "@/domains/projects"
import { StopOperationConfirm } from "@/domains/providers"
import type { ProviderTypeView } from "@/domains/providers"
import { ApiError } from "@/shared/api/http"
import { useScopedResource } from "@/shared/lib/useScopedResource"
import type { ScopedResource } from "@/shared/lib/useScopedResource"
import { ConfirmDialog } from "@/shared/ui/ConfirmDialog"
import { PageHeader } from "@/shared/ui/PageHeader"
import { useProjectProvidersController } from "../model/useProjectProvidersController"
import { usePoolOperation } from "../model/usePoolOperation"
import { ProjectCapacityDialog } from "./ProjectCapacityDialog"
import { ProjectProvidersContent } from "./ProjectProvidersContent"
import { ProviderOwnerLine } from "./ProviderOwnerLine"

type Dialog = { type: "add"; provider?: string } | { type: "edit" | "unassign"; pool: ProjectPool }

function renderDialogs({ isOwner, dialog, projectId, projectName, missing, pending, error, close, saved, unassign }: {
  isOwner: boolean
  dialog: Dialog | null
  projectId: string
  projectName: string
  missing: ProviderTypeView[]
  pending: boolean
  error: string | null
  close: () => void
  saved: () => void
  unassign: (pool: ProjectPool) => void
}) {
  return <>
    {isOwner && dialog?.type !== "unassign" && dialog !== null && <ProjectCapacityDialog
      projectId={projectId} projectName={projectName} providers={missing}
      provider={dialog.type === "add" ? dialog.provider : undefined} pool={dialog.type === "edit" ? dialog.pool : undefined}
      onClose={close} onSaved={saved} />}
    <ConfirmDialog open={isOwner && dialog?.type === "unassign"} title="Unassign pool"
      message="This pool will no longer serve this project" confirmLabel="Unassign" pending={pending} error={error}
      onClose={close} onConfirm={() => { if (dialog?.type === "unassign") unassign(dialog.pool) }} />
  </>
}

function withoutCapacity(providers: readonly ProviderTypeView[], pools: readonly ProjectPool[]) {
  return providers.filter((provider) => !provider.keyless && !provider.killSwitch && provider.systemEnabledOperations.length > 0 &&
    !pools.some((pool) => pool.provider_type === provider.providerType))
}

function providersForDialog(dialog: Dialog | null, providers: ProviderTypeView[], missing: ProviderTypeView[]) {
  if (dialog?.type !== "add" || !dialog.provider) return missing
  return providers.filter((provider) => provider.providerType === dialog.provider || missing.includes(provider))
}

function isCapacityOwner(owner: ScopedResource<ProviderOwner | null>, access: ProjectAccess | null, accountId: string) {
  return owner.status === "ready" && owner.data?.user_id === accountId &&
    hasPermission(access, PROJECT_PERMISSIONS.providersSupply)
}

function operationConfirmation(operation: ReturnType<typeof usePoolOperation>, projectName: string) {
  const change = operation.change
  if (!change) return null
  const remaining = change.operation === "search" ? "fetch" : "search"
  return <StopOperationConfirm provider={change.pool.provider_type} operation={change.operation} projectName={projectName}
    remaining={change.pool.operations.includes(remaining) ? remaining : undefined}
    pending={operation.pending} error={operation.error} onClose={operation.close} onConfirm={operation.confirm} />
}

function operationNotice(operation: ReturnType<typeof usePoolOperation>) {
  return operation.error && !operation.change ? <p role="alert">{operation.error}</p> : null
}

export function ProjectProvidersPage({ accountId }: { accountId: string }) {
  const { projectId, project, accessState, refreshAccess } = useProjectScope()
  const { systemAccess } = useProjectsOptional()
  const access = accessState.status === "ready" ? accessState.data : null
  const canConfigure = hasPermission(access, PROJECT_PERMISSIONS.providersConfigure)
  const isAdmin = access?.roles.includes("project_admin") ?? false
  const controller = useProjectProvidersController({ accountId, projectId })
  const owner = useScopedResource({ scopeKey: `${accountId}:${projectId}:owner`, load: (signal) => getProviderOwner(projectId, signal) })
  const pools = useScopedResource({ scopeKey: `${accountId}:${projectId}:pools`, load: (signal) => listProjectPools(projectId, signal) })
  const [dialog, setDialog] = useState<Dialog | null>(null)
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [revision, setRevision] = useState(0)
  const isOwner = isCapacityOwner(owner, access, accountId)
  const providers = controller.view.status === "ready" ? controller.view.data.providers : []
  const poolRows = pools.status === "ready" ? pools.data : []
  const missing = withoutCapacity(providers, poolRows)
  const dialogProviders = providersForDialog(dialog, providers, missing)
  const reload = () => {
    controller.reloadAll()
    void pools.reload()
    void owner.reload()
    refreshAccess()
    setRevision((value) => value + 1)
  }
  const unassign = async (pool: ProjectPool) => {
    setPending(true)
    setError(null)
    try {
      await detachProjectPool(projectId, pool.pool_id)
      setDialog(null)
      reload()
    } catch (failure) {
      setError(failure instanceof ApiError && failure.status === 404 ? "This action is not available yet" : "The pool could not be unassigned. Try again")
    } finally {
      setPending(false)
    }
  }
  const operation = usePoolOperation(reload)
  return <section className="flex flex-1 flex-col space-y-6">
    <PageHeader title="Providers" description="The providers this project uses and the pool that serves each one" />
    <ProviderOwnerLine owner={owner} projectId={projectId} accountId={accountId} isAdmin={isAdmin}
      canConfigure={canConfigure} onClaimed={reload} />
    {operationNotice(operation)}
    <ProjectProvidersContent projectId={projectId} revision={revision} controller={controller} owner={owner} pools={pools}
      missing={missing} isOwner={isOwner} canConfigure={canConfigure} canEditSystem={hasPermission(systemAccess, SYSTEM_PERMISSIONS.settingsWrite)} reload={reload}
      add={(provider) => setDialog({ type: "add", provider })}
      edit={(pool) => setDialog({ type: "edit", pool })}
      unassign={(pool) => { setError(null); setDialog({ type: "unassign", pool }) }}
      changeOperation={operation.toggle} operationPending={operation.pending} />
    {operationConfirmation(operation, project?.name ?? "this project")}
    {renderDialogs({ isOwner, dialog, projectId, projectName: project?.name ?? "this project", missing: dialogProviders, pending, error,
      close: () => setDialog(null), saved: () => { setDialog(null); reload() }, unassign: (pool) => void unassign(pool) })}
  </section>
}
