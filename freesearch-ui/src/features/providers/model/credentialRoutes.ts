import {
  createProjectCredential,
  createSystemCredential,
  deleteProjectCredential,
  deleteSystemCredential,
  disconnectCredentialOAuth,
  projectCredentialBase,
  rotateProjectCredential,
  rotateSystemCredential,
  systemCredentialBase,
} from "@/domains/providers"
import type { NewCredentialInput } from "@/domains/providers"

/** Row data the credential actions need. */
export interface CredentialRef {
  id: string
  label: string
  generation: number | null
}

/** Credential routes of one owner scope (system or one project). */
export interface CredentialRoutes {
  create: (input: NewCredentialInput) => Promise<unknown>
  rotate: (id: string, expectedGeneration: number, secret: string) => Promise<unknown>
  remove: (id: string) => Promise<void>
  disconnect: (id: string) => Promise<void>
  oauthBase: (id: string) => string
}

/** Credential routes of the system scope. */
export const SYSTEM_CREDENTIAL_ROUTES: CredentialRoutes = {
  create: createSystemCredential,
  rotate: rotateSystemCredential,
  remove: deleteSystemCredential,
  disconnect: (id) => disconnectCredentialOAuth(systemCredentialBase(id)),
  oauthBase: systemCredentialBase,
}

/** Credential routes of one project's private credentials. */
export function projectCredentialRoutes(projectId: string): CredentialRoutes {
  return {
    create: (input) => createProjectCredential(projectId, input),
    rotate: (id, expectedGeneration, secret) =>
      rotateProjectCredential(projectId, id, { expectedGeneration, secret }),
    remove: (id) => deleteProjectCredential(projectId, id),
    disconnect: (id) => disconnectCredentialOAuth(projectCredentialBase(projectId, id)),
    oauthBase: (id) => projectCredentialBase(projectId, id),
  }
}
