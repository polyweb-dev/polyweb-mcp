/**
 * Full project provider view and project binding routes.
 *
 * The view carries provider types (capability, system state, available
 * credentials, bindings) plus this project's own allocations. A new binding
 * always starts with nothing enabled; enabling is a separate update.
 */
import { requestJson } from "@/shared/api/client"
import { asRecord, decodeOne } from "@/shared/api/decode"
import { decodeAllocation } from "./capacityWire"
import { decodeBinding, decodeProviderTypeView } from "./credentialsWire"
import type { Allocation } from "../model/capacity"
import type { NewBindingInput, ProviderBinding, ProviderTypeView } from "../model/credentials"
import type { ProviderOperation } from "../model/projectProviders"

/** The project provider view plus its own allocations. */
export interface ProjectProviderView {
  providers: ProviderTypeView[]
  allocations: Allocation[]
}

function rows<T>(value: unknown, decode: (row: unknown) => T | null): T[] {
  if (!Array.isArray(value)) return []
  return value.map(decode).filter((row): row is T => row !== null)
}

/** Decode `ProjectProvidersRead`; rows that do not decode are dropped. */
export function decodeProjectProviderView(payload: unknown): ProjectProviderView {
  const record = asRecord(payload)
  if (record === null || !Array.isArray(record.providers)) {
    throw new Error("project provider view is not a list of providers")
  }
  return {
    providers: rows(record.providers, decodeProviderTypeView),
    allocations: rows(record.allocations, decodeAllocation),
  }
}

function bindingsBase(projectId: string): string {
  return `/api/v1/projects/${encodeURIComponent(projectId)}/bindings`
}

/** Read the full provider view of one project. */
export async function getProjectProviderView(
  projectId: string,
  signal?: AbortSignal
): Promise<ProjectProviderView> {
  const payload = await requestJson<unknown>(
    `/api/v1/projects/${encodeURIComponent(projectId)}/providers`,
    signal === undefined ? {} : { signal }
  )
  return decodeProjectProviderView(payload)
}

/** Create one binding; it starts with no enabled operation. */
export async function createBinding(
  projectId: string,
  input: NewBindingInput
): Promise<ProviderBinding> {
  const payload = await requestJson<unknown>(bindingsBase(projectId), {
    method: "POST",
    body: JSON.stringify({
      credential_id: input.credentialId,
      route_label: input.routeLabel,
      priority: input.priority,
    }),
  })
  return decodeOne(payload, decodeBinding, "binding")
}

/** Replace the enabled operations of one binding. */
export async function setBindingOperations(
  projectId: string,
  bindingId: string,
  operations: readonly ProviderOperation[]
): Promise<ProviderBinding> {
  const payload = await requestJson<unknown>(
    `${bindingsBase(projectId)}/${encodeURIComponent(bindingId)}`,
    { method: "PATCH", body: JSON.stringify({ enabled_operations: [...operations] }) }
  )
  return decodeOne(payload, decodeBinding, "binding")
}

/** Remove one binding. */
export async function deleteBinding(projectId: string, bindingId: string): Promise<void> {
  await requestJson<unknown>(`${bindingsBase(projectId)}/${encodeURIComponent(bindingId)}`, {
    method: "DELETE",
  })
}
