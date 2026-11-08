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

/** Legacy project-key actions are unavailable; keys belong to the account vault. */
export function projectCredentialRoutes(): CredentialRoutes {
  const unavailable = () => { throw new Error("Manage keys in Account > Keys and pools.") }
  return {
    create: async () => unavailable(),
    rotate: async () => unavailable(),
    remove: async () => unavailable(),
    disconnect: async () => unavailable(),
    oauthBase: unavailable,
  }
}
