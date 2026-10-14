import type {
  CRDConversionProfile,
  CRDOperation,
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
  operation: CRDOperation
  usdPerCall: string | null
  crdPerCall: string | null
  priceVersion: string | null
  estimated: boolean
  free: boolean
  priceBasis: string | null
}

interface PriceNoteDependencies {
  activeAuth: (limits: ProviderLimits, hasKey?: boolean) => ProviderAuthLimits | undefined
  usdFromCRD: (crd: string, profile: CRDConversionProfile) => string | null
  formatCRDAmount: (crd: string) => string
}

interface RuntimePrice {
  usdPerCall: string | null
  crdPerCall: string | null
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

const OPERATIONS: readonly CRDOperation[] = ["search", "fetch"]
const RUNTIME_PRICE_BASES: Readonly<Record<string, Partial<Record<CRDOperation, string>>>> = {
  brave: { search: "per search request" },
  keenable: { search: "per request", fetch: "per request" },
  tinyfish: { search: "per search request", fetch: "per fetch request" },
  exa: { search: "per search request", fetch: "per page, per content type" },
  firecrawl: { search: "per search request", fetch: "per fetched page" },
  tavily: { search: "per search request", fetch: "per successful URL" },
  parallel: { search: "per search request", fetch: "per extracted URL" },
  youcom: { search: "per search request", fetch: "per live page" },
}

function recordFor(auth: ProviderAuthLimits, operation: CRDOperation): LimitRecord | null {
  return operation === "search" ? auth.search : auth.fetch
}

function runtimePrice(
  auth: ProviderAuthLimits | undefined,
  operation: CRDOperation,
  dependencies: PriceNoteDependencies,
): RuntimePrice | null {
  if (auth === undefined) return null
  const record = recordFor(auth, operation)
  if (record === null || !record.supported) return null
  const view = auth.crd_views.find((entry) => entry.operation === operation)
  const crd = view?.request_cost_crd
  if (crd === null || crd === undefined) return null
  const usd = dependencies.usdFromCRD(crd, record.conversion_profile)
  const version = record.conversion_profile.price_version
  return {
    usdPerCall: usd,
    crdPerCall: dependencies.formatCRDAmount(crd),
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

/** Only explicit zero or noncharging limit facts make a runtime rail free. */
function runtimeFreeOperation(
  auth: ProviderAuthLimits | undefined,
  operation: CRDOperation,
): boolean {
  if (auth === undefined) return false
  const record = recordFor(auth, operation)
  const view = auth.crd_views.find((entry) => entry.operation === operation)
  if (isZero(view?.request_cost_crd) || isZero(record?.budget?.usd_per_call)) return true
  return view?.state === "unmetered" && view.priced === false && record?.budget?.model === "none"
}

function runtimePriceBasis(provider: string, operation: CRDOperation): string {
  return RUNTIME_PRICE_BASES[provider]?.[operation] ?? `per ${operation} request`
}

function supportedRecord(
  provider: PriceProvider,
  auth: ProviderAuthLimits | undefined,
  operation: CRDOperation,
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
  operation: CRDOperation,
  free: boolean,
  documented: NonNullable<ReturnType<typeof documentedProviderPrice>>,
): PriceNoteRow {
  return {
    provider: provider.id,
    providerName: provider.name,
    operation,
    usdPerCall: documented.usdPerCall,
    crdPerCall: documented.crdPerCall,
    priceVersion: DOCUMENTED_PRICE_VERSION,
    estimated: documented.usdPerCall !== null,
    free,
    priceBasis: documented.priceBasis,
  }
}

function freeRow(
  provider: PriceProvider,
  operation: CRDOperation,
  record: LimitRecord | null | undefined,
): PriceNoteRow {
  return {
    provider: provider.id,
    providerName: provider.name,
    operation,
    usdPerCall: null,
    crdPerCall: null,
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
  operation: CRDOperation
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
