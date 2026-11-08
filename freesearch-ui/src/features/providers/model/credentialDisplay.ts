/**
 * How one credential reads on the project Providers page: its source as a
 * short tag, and whether it is the keyless public tier of a provider.
 */
import { catalogEntryForId } from "@/domains/providers"
import type { AvailableCredential } from "@/domains/providers"

/**
 * A keyless credential: its provider documents a keyless tier and the key is
 * labelled as keyless. The credential view carries no explicit flag yet.
 */
export function isKeylessCredential(providerType: string, credential: Pick<AvailableCredential, "label" | "authMode">): boolean {
  const keylessTier = catalogEntryForId(providerType)?.capabilities.includes("keyless_tier") === true
  return keylessTier && credential.authMode !== "oauth" && /keyless/i.test(credential.label)
}

/** Sentence case of a backend word such as `active` or `rate_limited`. */
export function readableWord(value: string): string {
  const spaced = value.replaceAll("_", " ")
  return spaced.length === 0 ? spaced : spaced[0].toUpperCase() + spaced.slice(1)
}
