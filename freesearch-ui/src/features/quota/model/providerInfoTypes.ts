import type { CreditMode } from "./quotaLabels"

/** One popover row: the fact label, its main value, and an optional quiet part. */
export interface ProviderInfoFact {
  label: string
  value: string
  note: string | null
}

/** Facts and usage link of one card info popover. */
export interface ProviderInfo {
  facts: ProviderInfoFact[]
  usageUrl: string | null
  /** The credit note of the popover header: the tier, the period, and the unit. */
  creditNote: string | null
  /** The credit tier of the rail; an absent tier yields null. */
  creditMode: CreditMode | null
  /** The funds source of the card subtitle; an absent source yields null. */
  statement: string | null
}

/** The observed native funds of one rail: the estimate start of a new entry. */
export interface BalancePrefill {
  allowance: string
  remaining: string
}

