/**
 * Per-provider display rules of the usage cards.
 *
 * Every card shares one layout: the same header, the same bar block, and the
 * same footer. The few provider differences live in this one map instead of
 * branches inside the card.
 */

export interface ProviderCardRule {
  /** Rate rows collapse to one row per bucket, with counts in the hover text. */
  sharedRateBars: boolean
  /** One title for every rate row of the card. */
  sharedRateTitle: string | null
  /** Request counts of the popover floor to whole calls. */
  wholeRequests: boolean
  /** A keyless rail has no usage endpoint, so the card shows no Refresh. */
  keylessHasNoUsage: boolean
  /** The card holds no rate bars; its native Credits bar says it all. */
  noRateBars: boolean
  /** The card holds the composed rate-tier control. */
  rateTier: boolean
}

const DEFAULT_RULE: ProviderCardRule = {
  sharedRateBars: false,
  sharedRateTitle: null,
  wholeRequests: false,
  keylessHasNoUsage: false,
  noRateBars: false,
  rateTier: false,
}

const RULES: Readonly<Record<string, Partial<ProviderCardRule>>> = {
  keenable: {
    sharedRateBars: true,
    sharedRateTitle: "Search and fetch",
    wholeRequests: true,
    keylessHasNoUsage: true,
  },
  tinyfish: { sharedRateBars: true },
  tavily: { keylessHasNoUsage: true, noRateBars: true, rateTier: true },
  firecrawl: { keylessHasNoUsage: true },
  parallel: { keylessHasNoUsage: true },
  youcom: { keylessHasNoUsage: true },
}

/** The display rule of one provider card; an unlisted provider takes the default. */
export function providerCardRule(providerId: string): ProviderCardRule {
  return { ...DEFAULT_RULE, ...RULES[providerId] }
}

/** Distinguish a missing provider balance from locally recorded usage. */
export function emptyUsageText(needsCredential: boolean, keyless = false): string {
  if (keyless) return "Keyless · provider balance not reported"
  return needsCredential ? "Add a system key to see usage" : "Provider balance not reported"
}
