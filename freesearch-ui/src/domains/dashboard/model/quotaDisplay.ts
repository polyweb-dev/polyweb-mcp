import { unitLabel, type UnitKind } from "@/shared/api/units"
import type { ProviderConfig } from "@/domains/providers/model/types";import type { DashboardQuota, QuotaConfidence } from "./quotaTypes";

/**
 * The quota headline is deliberately provider-neutral: when both values are
 * known, every provider can be compared as remaining capacity from 0–100%.
 * Native values remain strings so decimal formatting from the vendor is not
 * rewritten (or accidentally rendered in exponential notation).
 */
export interface QuotaDisplayInput {
  remaining: string | null
  remainingPercent?: string | null
  limit: string | null
  unitKind: UnitKind | null
  displayUnit: string | null
  confidence: QuotaConfidence | null
  resetAt: string | null
  providerId?: string
  keyless?: boolean
  window?: string | null
  isOAuthPaired?: boolean
}

export interface QuotaDisplay {
  remainingPercent: number | null
  headline: string
  periodLabel: string
  nativeLabel: string
  nativeValue: string
  confidenceLabel: string
  resetLabel: string | null
  detail: string | null
  hasFiniteLimit: boolean
}

/** Remaining-only balances read as account balances, never as budgets. */
function isBalancePeriod(input: QuotaDisplayInput): boolean {
  if (input.providerId === "you" || input.providerId === "youcom") return true
  return (
    input.providerId === "parallel" &&
    (input.confidence === "authoritative" || Boolean(input.isOAuthPaired)) &&
    input.limit === null
  )
}

function periodLabel(input: QuotaDisplayInput): string {
  const normalizedWindow = input.window?.trim().toLowerCase()
  if (normalizedWindow === "hourly" || normalizedWindow === "hour") return "Hourly"
  if (normalizedWindow === "monthly" || normalizedWindow === "month") return "Monthly"
  if (isBalancePeriod(input)) return "Account balance"
  if (input.providerId === "keenable" && input.keyless) return "Hourly"
  if (["brave", "exa", "firecrawl", "keenable", "parallel", "tavily", "tinyfish"].includes(input.providerId ?? "")) {
    return "Monthly"
  }
  return "Quota"
}

/** A remaining balance with no percentage reads as available funds. */
function isBalanceHeadline(input: QuotaDisplayInput, remaining: number | null): boolean {
  if (remaining === null) return false
  if (input.providerId === "you" || input.providerId === "youcom") return true
  return input.providerId === "parallel" && input.confidence === "authoritative"
}

function quotaHeadline(input: QuotaDisplayInput, percent: number | null, remaining: number | null): string {
  if (percent !== null) return `${percent}% remaining`
  if (isBalanceHeadline(input, remaining)) return "Balance available"
  if (input.providerId === "parallel" && input.isOAuthPaired) return "Balance pending"
  if (["exa", "parallel", "tinyfish"].includes(input.providerId ?? "")) return "Budget not configured"
  if (input.providerId === "brave") return "Limit unavailable"
  if (input.providerId === "keenable") return input.keyless ? "Hourly quota pending" : "Quota pending"
  return "Quota unavailable"
}

function nativeValue(input: QuotaDisplayInput, nativeLabel: string): string {
  if (input.remaining === null && input.limit === null) {
    if (input.providerId === "parallel" && input.isOAuthPaired) return "OAuth connected"
    if (input.providerId === "exa" || input.providerId === "parallel") return "USD spend tracked separately"
    if (input.providerId === "brave") return "Monthly request limit unavailable"
    if (input.providerId === "keenable" && input.keyless) return "Hourly request counter unavailable"
  }
  return `${input.remaining ?? "—"}/${input.limit ?? "—"} ${nativeLabel}`
}


function finiteNumber(value: string | null): number | null {
  if (value === null || value.trim() === "") return null
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : null
}

function resetLabel(resetAt: string | null): string | null {
  if (!resetAt) return null
  const date = new Date(resetAt)
  if (Number.isNaN(date.getTime())) return resetAt
  return date.toLocaleDateString(undefined, { month: "short", day: "numeric" })
}

function remainingPercent(input: QuotaDisplayInput, remaining: number | null, limit: number | null): number | null {
  if (remaining === null || limit === null || limit <= 0) return null
  const supplied = finiteNumber(input.remainingPercent ?? null)
  const raw = supplied ?? (remaining / limit) * 100
  return Math.round(Math.min(100, Math.max(0, raw)) * 10) / 10
}

function quotaDetail(input: QuotaDisplayInput, nativeLabel: string): string | null {
  if (input.keyless) {
    return input.window
      ? `Keyless ${input.window} request headroom (locally observed); shared rate limits still apply.`
      : "Keyless shared pool (locally observed); rate-limited and not a monthly allowance."
  }
  if (input.limit !== null && input.remaining !== null) return null
  return input.remaining === null
    ? null
    : `No hard limit reported; showing remaining ${nativeLabel} balance.`
}

/**
 * Unit name of one quota value. Tavily native values are vendor `Credits`
 * (one native CREDIT unit), which keeps every Tavily message in Credits, never
 * CRD and never the generic "credits" lowercase label. Every other provider
 * keeps the shared unit label.
 */
function nativeLabel(input: QuotaDisplayInput): string {
  if (input.providerId === "tavily" && input.unitKind === "CREDIT") return "Credits"
  return unitLabel(input.unitKind, input.displayUnit)
}

/** Build the consistent headline/detail values used by every quota surface. */
export function quotaDisplay(input: QuotaDisplayInput): QuotaDisplay {
  const remainingNumber = finiteNumber(input.remaining)
  const limitNumber = finiteNumber(input.limit)
  const hasFiniteLimit = remainingPercent(input, remainingNumber, limitNumber) !== null
  // Keep useful fractional headroom (997/1000 → 99.7%), while avoiding
  // noisy vendor precision in the headline. Never expose a percentage unless
  // native remaining and limit are both finite and the limit is positive.
  const percent = remainingPercent(input, remainingNumber, limitNumber)
  const shownLabel = nativeLabel(input)
  const nativeQuotaValue = nativeValue(input, shownLabel)
  const confidenceLabel = input.confidence ?? "not reported"
  const detail = quotaDetail(input, shownLabel)

  return {
    remainingPercent: percent,
    headline: quotaHeadline(input, percent, remainingNumber),
    periodLabel: periodLabel(input),
    nativeLabel: shownLabel,
    nativeValue: nativeQuotaValue,
    confidenceLabel,
    resetLabel: resetLabel(input.resetAt),
    detail,
    hasFiniteLimit,
  }
}

/** Keyless detection shared by every provider-only quota normalization. */
export function isKeylessQuotaProvider(provider: ProviderConfig): boolean {
  return (
    provider.id === "keenable" &&
    (provider.keyVaultStatus === "keyless_public" || provider.keySource === "none")
  )
}

/**
 * Absent-snapshot predicate shared by quota captions and row decisions.
 * A snapshot with both natives null carries no budget signal, exactly like
 * a missing snapshot; a half-null snapshot is still a snapshot and must
 * flow through wholesale (never resurrect older balances).
 */
export function isMissingQuotaSnapshot(quota: DashboardQuota | undefined): boolean {
  return quota === undefined || (quota.remaining === null && quota.limit === null)
}

/**
 * Canonical provider-only quota input. Centralizes the confidence guard
 * (unobserved base values carry no signal), the legacy "—" reset guard,
 * and keyless detection so feature overlays never re-derive them.
 */
export function providerQuotaInput(provider: ProviderConfig): QuotaDisplayInput {
  const quota = provider.quota
  return {
    remaining: quota.remaining,
    remainingPercent: quota.remainingPercent,
    limit: quota.limit,
    unitKind: quota.unitKind,
    displayUnit: quota.displayUnit,
    confidence: quota.observedAt ? quota.confidence : null,
    resetAt: quota.nextReset !== "—" ? quota.nextReset : null,
    providerId: provider.id,
    keyless: isKeylessQuotaProvider(provider),
    window: quota.window,
  }
}

/** Resolve one provider's dashboard-overlaid quota into display data. */
export function providerQuotaDisplay(provider: ProviderConfig): QuotaDisplay {
  return quotaDisplay(providerQuotaInput(provider))
}
