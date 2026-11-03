/**
 * Credential instance routes: system credentials, their project grants,
 * project private credentials and the credential-scoped OAuth device flow.
 *
 * A secret goes out in exactly one request body (create or rotate) and is
 * never returned, logged or cached here. Every response is decoded from
 * `unknown` through the safe-field decoders.
 */
import { requestJson } from "@/shared/api/client"
import { decodeList, decodeOne } from "@/shared/api/decode"
import {
  decodeGrant,
  decodeOAuthDevice,
  decodeOAuthStatus,
  decodeProjectCredential,
  decodeSystemCredential,
} from "./credentialsWire"
import type {
  CredentialGrant,
  NewCredentialInput,
  OAuthDeviceStart,
  OAuthStatus,
  ProjectCredential,
  SystemCredential,
} from "../model/credentials"
import type { ProviderOperation } from "../model/projectProviders"

const SYSTEM_BASE = "/api/v1/system/credentials"

function segment(value: string): string {
  return encodeURIComponent(value)
}

function signalInit(signal?: AbortSignal): RequestInit {
  return signal === undefined ? {} : { signal }
}

/** Base path of one system credential. */
export function systemCredentialBase(credentialId: string): string {
  return `${SYSTEM_BASE}/${segment(credentialId)}`
}

/** Base path of one credential as seen from one project. */
export function projectCredentialBase(projectId: string, credentialId: string): string {
  return `/api/v1/projects/${segment(projectId)}/credentials/${segment(credentialId)}`
}

function createBody(input: NewCredentialInput): string {
  const body: Record<string, unknown> = {
    provider_type: input.providerType,
    label: input.label,
    auth_mode: input.authMode,
  }
  if (input.authMode === "api_key") body.secret = input.secret
  return JSON.stringify(body)
}

function rotateBody(expectedGeneration: number, secret: string): string {
  return JSON.stringify({ expected_generation: expectedGeneration, secret })
}

/** List the system credentials. */
export async function listSystemCredentials(signal?: AbortSignal): Promise<SystemCredential[]> {
  const payload = await requestJson<unknown>(SYSTEM_BASE, signalInit(signal))
  return decodeList(payload, decodeSystemCredential, "system credential list")
}

/** Create one system credential. */
export async function createSystemCredential(input: NewCredentialInput): Promise<SystemCredential> {
  const payload = await requestJson<unknown>(SYSTEM_BASE, { method: "POST", body: createBody(input) })
  return decodeOne(payload, decodeSystemCredential, "system credential")
}

/** Rotate one system credential at its expected generation. */
export async function rotateSystemCredential(
  credentialId: string,
  expectedGeneration: number,
  secret: string
): Promise<SystemCredential> {
  const payload = await requestJson<unknown>(`${systemCredentialBase(credentialId)}/rotate`, {
    method: "POST",
    body: rotateBody(expectedGeneration, secret),
  })
  return decodeOne(payload, decodeSystemCredential, "system credential")
}

/** Delete one system credential. */
export async function deleteSystemCredential(credentialId: string): Promise<void> {
  await requestJson<unknown>(systemCredentialBase(credentialId), { method: "DELETE" })
}

/** List the project grants of one system credential. */
export async function listCredentialGrants(
  credentialId: string,
  signal?: AbortSignal
): Promise<CredentialGrant[]> {
  const payload = await requestJson<unknown>(
    `${systemCredentialBase(credentialId)}/grants`,
    signalInit(signal)
  )
  return decodeList(payload, decodeGrant, "credential grant list")
}

/** Create or replace one project grant. */
export async function putCredentialGrant(
  credentialId: string,
  projectId: string,
  operations: readonly ProviderOperation[]
): Promise<CredentialGrant> {
  const payload = await requestJson<unknown>(
    `${systemCredentialBase(credentialId)}/grants/${segment(projectId)}`,
    { method: "PUT", body: JSON.stringify({ permitted_operations: [...operations] }) }
  )
  return decodeOne(payload, decodeGrant, "credential grant")
}

/** Remove one project grant. */
export async function deleteCredentialGrant(credentialId: string, projectId: string): Promise<void> {
  await requestJson<unknown>(`${systemCredentialBase(credentialId)}/grants/${segment(projectId)}`, {
    method: "DELETE",
  })
}

/** List the credentials one project can see. */
export async function listProjectCredentials(
  projectId: string,
  signal?: AbortSignal
): Promise<ProjectCredential[]> {
  const payload = await requestJson<unknown>(
    `/api/v1/projects/${segment(projectId)}/credentials`,
    signalInit(signal)
  )
  return decodeList(payload, decodeProjectCredential, "project credential list")
}

/** Create one private project credential. */
export async function createProjectCredential(
  projectId: string,
  input: NewCredentialInput
): Promise<ProjectCredential> {
  const payload = await requestJson<unknown>(`/api/v1/projects/${segment(projectId)}/credentials`, {
    method: "POST",
    body: createBody(input),
  })
  return decodeOne(payload, decodeProjectCredential, "project credential")
}

/** Rotate one private project credential at its expected generation. */
export async function rotateProjectCredential(
  projectId: string,
  credentialId: string,
  options: { expectedGeneration: number; secret: string }
): Promise<ProjectCredential> {
  const payload = await requestJson<unknown>(
    `${projectCredentialBase(projectId, credentialId)}/rotate`,
    { method: "POST", body: rotateBody(options.expectedGeneration, options.secret) }
  )
  return decodeOne(payload, decodeProjectCredential, "project credential")
}

/** Delete one private project credential. */
export async function deleteProjectCredential(projectId: string, credentialId: string): Promise<void> {
  await requestJson<unknown>(projectCredentialBase(projectId, credentialId), { method: "DELETE" })
}

/** Start the OAuth device flow of one credential (system or project base). */
export async function startCredentialOAuth(
  base: string,
  signal?: AbortSignal
): Promise<OAuthDeviceStart> {
  const payload = await requestJson<unknown>(`${base}/oauth/device`, {
    method: "POST",
    ...signalInit(signal),
  })
  return decodeOne(payload, decodeOAuthDevice, "OAuth device flow")
}

/** Poll the OAuth device flow of one credential once. */
export async function pollCredentialOAuth(base: string, signal?: AbortSignal): Promise<OAuthStatus> {
  const payload = await requestJson<unknown>(`${base}/oauth/poll`, {
    method: "POST",
    ...signalInit(signal),
  })
  return decodeOne(payload, decodeOAuthStatus, "OAuth status")
}

/** Disconnect the OAuth grant of one credential. */
export async function disconnectCredentialOAuth(base: string): Promise<void> {
  await requestJson<unknown>(`${base}/oauth`, { method: "DELETE" })
}
