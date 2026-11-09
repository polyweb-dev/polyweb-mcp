import type {
  UsdOperation,
  LimitRecord,
  ProviderAuthLimits,
  ProviderLimits,
} from "@/domains/dashboard"
import type { ProviderConfig } from "@/domains/providers"
import {
  DOCUMENTED_PRICE_VERSION,
  documentedProviderPrice,
  isDocumentedFreeOperation,
} from "./documentedProviderPrices"
import { parseDecimal } from "./manualQuotaMath"

/** Input of the page price note. */
export interface PriceNoteInput {
  providers: ProviderConfig[]
  providerLimits: ProviderLimits[]
}

/** One supported operation price of one provider. */
export interface PriceNoteRow {
  provider: string
  providerName: string
  operation: UsdOperation
  usdPerCall: string | null
  priceVersion: string | null
  estimated: boolean
  free: boolean
  priceBasis: string | null
}

interface PriceNoteDependencies {
  activeAuth: (limits: ProviderLimits, hasKey?: boolean) => ProviderAuthLimits | undefined
  formatUsdAmount: (usd: string) => string
}

interface RuntimePrice {
  usdPerCall: string | null
  priceVersion: string | null
  estimated: boolean
}

interface PriceProvider {
  id: string
  name: string
  hasKey?: boolean
  keyVaultStatus?: string | null
  capabilities: readonly string[]
}

const OPERATIONS: readonly UsdOperation[] = ["search", "fetch"]
const RUNTIME_PRICE_BASES: Readonly<Record<string, Partial<Record<UsdOperation, string>>>> = {
  brave: { search: "per search request" },
  keenable: { search: "per request", fetch: "per request" },
  tinyfish: { search: "per search request", fetch: "per fetch request" },
  exa: { search: "per search request", fetch: "per page, per content type" },
  firecrawl: { search: "per search request", fetch: "per fetched page" },
  tavily: { search: "per search request", fetch: "per successful URL" },
  parallel: { search: "per search request", fetch: "per extracted URL" },
  youcom: { search: "per search request", fetch: "per live page" },
}

function recordFor(auth: ProviderAuthLimits, operation: UsdOperation): LimitRecord | null {
  return operation === "search" ? auth.search : auth.fetch
}

function runtimePrice(
  auth: ProviderAuthLimits | undefined,
  operation: UsdOperation,
  dependencies: PriceNoteDependencies,
): RuntimePrice | null {
  if (auth === undefined) return null
  const record = recordFor(auth, operation)
  if (record === null || !record.supported) return null
  const view = auth.usd_views.find((entry) => entry.operation === operation)
  const usd = view?.request_cost_usd
  if (usd === null || usd === undefined) return null
  const version = record.conversion_profile.price_version
  return {
    usdPerCall: dependencies.formatUsdAmount(usd),
    priceVersion: version === "" ? null : version,
    estimated: record.conversion_profile.estimated,
  }
}

function credentialPresence(provider: PriceProvider): boolean | undefined {
  if (provider.id !== "tavily") return provider.hasKey
  if (provider.keyVaultStatus === undefined || provider.keyVaultStatus === null) return undefined
  return provider.keyVaultStatus === "configured"
}

function authModeFor(
  provider: PriceProvider,
  auth: ProviderAuthLimits | undefined,
): string {
  if (auth !== undefined) return auth.auth_mode
  if (provider.id === "tavily") {
    if (provider.keyVaultStatus === "configured") return "keyed"
    if (provider.keyVaultStatus === "keyless_public" || provider.keyVaultStatus === "missing") return "keyless"
    return "unknown"
  }
  if (provider.keyVaultStatus === "keyless_public") return "keyless"
  if (provider.hasKey === true || provider.keyVaultStatus === "configured") return "keyed"
  if (
    provider.hasKey === false &&
    (provider.capabilities.includes("keyless_tier") || provider.id === "tavily")
  ) {
    return "keyless"
  }
  return "unknown"
}

function isZero(value: string | null | undefined): boolean {
  const amount = value === null || value === undefined ? null : parseDecimal(value)
  return amount !== null && amount.int === 0n
}

function freeRecord(record: LimitRecord | null): boolean {
  if (record === null) return false
  return ["unbilled_free", "unbilled_keyless"].includes(record.conversion_profile.source)
    || isZero(record.budget?.usd_per_call)
}

/** Only explicit zero or noncharging limit facts make a runtime rail free. */
function runtimeFreeOperation(
  auth: ProviderAuthLimits | undefined,
  operation: UsdOperation,
): boolean {
  if (auth === undefined) return false
  const record = recordFor(auth, operation)
  const view = auth.usd_views.find((entry) => entry.operation === operation)
  if (freeRecord(record) || isZero(view?.request_cost_usd)) return true
  return view?.state === "unmetered" && view.priced === false && record?.budget?.model === "none"
}

function runtimePriceBasis(provider: string, operation: UsdOperation): string {
  return RUNTIME_PRICE_BASES[provider]?.[operation] ?? `per ${operation} request`
}

function supportedRecord(
  provider: PriceProvider,
  auth: ProviderAuthLimits | undefined,
  operation: UsdOperation,
): LimitRecord | null | undefined {
  const record = auth === undefined ? null : recordFor(auth, operation)
  if (record === null) return provider.capabilities.includes(operation) ? null : undefined
  return record.supported ? record : undefined
}

function showDocumentedReference(
  documentedFree: boolean,
  wireFree: boolean,
  documented: ReturnType<typeof documentedProviderPrice>,
): boolean {
  return documentedFree || (wireFree && documented !== null && documented.usdPerCall !== null)
}

function documentedRow(
  provider: PriceProvider,
  operation: UsdOperation,
  free: boolean,
  documented: NonNullable<ReturnType<typeof documentedProviderPrice>>,
): PriceNoteRow {
  return {
    provider: provider.id,
    providerName: provider.name,
    operation,
    usdPerCall: documented.usdPerCall,
    priceVersion: DOCUMENTED_PRICE_VERSION,
    estimated: documented.usdPerCall !== null,
    free,
    priceBasis: documented.priceBasis,
  }
}

function freeRow(
  provider: PriceProvider,
  operation: UsdOperation,
  record: LimitRecord | null | undefined,
): PriceNoteRow {
  return {
    provider: provider.id,
    providerName: provider.name,
    operation,
    usdPerCall: null,
    priceVersion: record?.conversion_profile.price_version || null,
    estimated: record?.conversion_profile.estimated ?? false,
    free: true,
    priceBasis: "Reported free",
  }
}

interface OperationPriceInput {
  provider: PriceProvider
  auth: ProviderAuthLimits | undefined
  authMode: string
  operation: UsdOperation
  dependencies: PriceNoteDependencies
}

function operationRow({
  provider,
  auth,
  authMode,
  operation,
  dependencies,
}: OperationPriceInput): PriceNoteRow | null {
  const record = supportedRecord(provider, auth, operation)
  if (record === undefined) return null

  const documented = documentedProviderPrice(provider.id, operation)
  const documentedFree = isDocumentedFreeOperation(provider.id, operation, authMode)
  const wireFree = runtimeFreeOperation(auth, operation)
  const free = documentedFree || wireFree
  if (!showDocumentedReference(documentedFree, wireFree, documented)) {
    const runtime = runtimePrice(auth, operation, dependencies)
    if (runtime !== null) {
      return {
        provider: provider.id,
        providerName: provider.name,
        operation,
        ...runtime,
        free,
        priceBasis: runtimePriceBasis(provider.id, operation),
      }
    }
  }
  if (documented !== null) return documentedRow(provider, operation, free, documented)
  return free ? freeRow(provider, operation, record) : null
}

function providerRow(
  provider: PriceProvider,
  limits: ProviderLimits | undefined,
  dependencies: PriceNoteDependencies,
): PriceNoteRow[] {
  const auth = limits === undefined ? undefined : dependencies.activeAuth(limits, credentialPresence(provider))
  const authMode = authModeFor(provider, auth)
  const rows: PriceNoteRow[] = []
  for (const operation of OPERATIONS) {
    const row = operationRow({ provider, auth, authMode, operation, dependencies })
    if (row !== null) rows.push(row)
  }
  return rows
}

/** Build price rows from active runtime facts and dated provider references. */
export function buildPriceNoteRows(
  input: PriceNoteInput,
  dependencies: PriceNoteDependencies,
): PriceNoteRow[] {
  const limitsByProvider = new Map(input.providerLimits.map((limits) => [limits.provider, limits]))
  const providers: PriceProvider[] = input.providers.map((provider) => ({
    id: provider.id,
    name: provider.name,
    hasKey: provider.hasKey,
    keyVaultStatus: provider.keyVaultStatus,
    capabilities: provider.capabilities,
  }))
  const configuredIds = new Set(providers.map((provider) => provider.id))

  for (const limits of input.providerLimits) {
    if (configuredIds.has(limits.provider)) continue
    providers.push({ id: limits.provider, name: limits.provider, capabilities: [] })
  }

  return providers.flatMap((provider) =>
    providerRow(provider, limitsByProvider.get(provider.id), dependencies),
  )
}
