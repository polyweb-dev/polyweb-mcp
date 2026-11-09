import type { ProviderConfig } from "./types";

/** Access mask bit 0: the admin master switch for the provider. */
export const GLOBAL_BIT = 1;
/** Access mask bit 1: the search operation. */
export const SEARCH_BIT = 2;
/** Access mask bit 2: the fetch operation. */
export const FETCH_BIT = 4;
/** Every known access mask bit set. */
export const ALL_BITS = GLOBAL_BIT | SEARCH_BIT | FETCH_BIT;

/** Raw admin choices and the system tool support mask of one provider. */
export interface ProviderAccessView {
  enableMask: number;
  supportMask: number;
  globalEnabled: boolean;
  searchEnabled: boolean;
  fetchEnabled: boolean;
}

/** Reject any value that is not an integer mask in the range 0..7. */
function decodeMask(field: string, value: unknown): number {
  if (
    typeof value !== "number" ||
    !Number.isInteger(value) ||
    value < 0 ||
    (value & ~ALL_BITS) !== 0
  ) {
    throw new Error(`${field} must be an integer number in the range 0..${ALL_BITS}`);
  }
  return value;
}

/**
 * Decode both access masks of one provider status row.
 * The result holds the raw admin choices of `enableMask` only.
 * The function never falls back to a default ON value.
 */
export function decodeProviderAccess(
  enableMask: unknown,
  supportMask: unknown,
): ProviderAccessView {
  const enable = decodeMask("enable_mask", enableMask);
  const support = decodeMask("support_mask", supportMask);
  return {
    enableMask: enable,
    supportMask: support,
    globalEnabled: (enable & GLOBAL_BIT) !== 0,
    searchEnabled: (enable & SEARCH_BIT) !== 0,
    fetchEnabled: (enable & FETCH_BIT) !== 0,
  };
}

/**
 * Effective access predicate: enable mask AND support mask must both grant the
 * global bit and the requested operation bit.
 */
export function isProviderOperationEnabled(
  provider: Pick<ProviderConfig, "enableMask" | "supportMask">,
  operation: "search" | "fetch",
): boolean {
  const effective = provider.enableMask & provider.supportMask;
  if ((effective & GLOBAL_BIT) === 0) return false;
  if (operation === "search") {
    return (effective & (GLOBAL_BIT | SEARCH_BIT)) === (GLOBAL_BIT | SEARCH_BIT);
  }
  if (operation === "fetch") {
    return (effective & (GLOBAL_BIT | FETCH_BIT)) === (GLOBAL_BIT | FETCH_BIT);
  }
  return false;
}
