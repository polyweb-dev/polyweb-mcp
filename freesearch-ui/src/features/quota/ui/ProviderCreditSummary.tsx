import type { ReactNode } from "react"
import { RemainingBar, percentLabel } from "@/shared/ui/RemainingBar"
import { dollarText, formatCRDAmount, percentRemaining } from "../model/crdDisplay"
import type { CreditCardModel } from "../model/crdCardModel"
import { formatCreditValue, type TavilyCreditsDisplay } from "../model/tavilyCredits"
import { Footnote } from "./Footnote"

export interface ProviderCreditSummaryProps {
  providerName: string
  model: CreditCardModel
  /**
   * Optional native display facts of one rail. The Tavily card passes its
   * Credits facts here; every other card leaves them absent and keeps the
   * current CRD fraction unchanged.
   */
  credits?: TavilyCreditsDisplay
  /** The action row that sits at the leading edge of the credit row. */
  actions?: ReactNode
  /** The info control that sits beside the credit fraction. */
  info?: ReactNode
  /** Optional explanatory notes rendered before the credit actions. */
  bodyNotes?: ReactNode
  /** Draw the funds bar of a finite rail through the shared bar. */
  useSharedBar?: boolean
  /** Optional control row rendered before a native credit progress bar. */
  fundsControl?: ReactNode
  /** Rate progress bars rendered above the action row. */
  rateBars?: ReactNode
  /**
   * Authoritative OAuth balance fallback (raw USD decimal, e.g. Parallel
   * Account-API remaining or You.com cents-balance remaining). Shown
   * amount-only when the limits model holds no funds; with a display-only
   * allowance it shows a fraction, bar, and capped percent instead. Only
   * Parallel and You.com produce this shape today (aggregate_pool null +
   * remaining-only latestQuota), so other cards leave it absent.
   */
  balanceFallbackUSD?: string | null
  /**
   * CRD equivalent of the fallback balance (exact decimal, e.g. "24870" for
   * USD 24.87 at the USD 0.001 reference). Computed by the card from the
   * rail profile through `usdBalanceToCRD`; the summary only formats it.
   * Absent when the conversion is unavailable, and the dollar amount still
   * shows alone.
   */
  balanceFallbackCRD?: string | null
  /**
   * Display-only allowance of the fallback balance (exact CRD decimal, e.g.
   * Parallel "$5/mo free credit" as "5000" or You.com "$100 signup" as
   * "100000"). Frontend-only; never a backend allowance. With both CRD
   * amounts known, the card shows the "remaining / allowance CRD" fraction
   * with a capped bar and percent; otherwise the fallback stays amount-only.
   */
  balanceFallbackAllowanceCRD?: string | null
}

const AMOUNT = "tnum text-[18px] font-semibold text-[var(--text-strong)]"
const TOTAL = "tnum text-[18px] font-semibold text-[var(--muted)]"
/** The unit keeps the size of the two amounts, with the quiet color. */
const UNIT = "text-[18px] font-semibold text-[var(--muted)]"
const CRD_SUFFIX = " CRD"
const CREDIT_ROW = "flex w-full flex-wrap items-center justify-between gap-3"
const CREDIT_VALUE = "ml-auto inline-flex h-8 shrink-0 items-center gap-1.5 leading-none"
/** The quiet state text of one native Credits rail. */
const VALUE = "text-[13px] text-[var(--muted)]"

/** The number part of one shown credit amount: "4500 CRD" becomes "4500". */
function amountNumber(amount: string): string {
  const text = formatCRDAmount(amount)
  return text.endsWith(CRD_SUFFIX) ? text.slice(0, -CRD_SUFFIX.length) : text
}

/** The credit amount of one rail: the fraction, the plain amount, or Free. */
function creditValue(model: CreditCardModel, usdLeft: string | null): ReactNode {
  if (model.state === "unmetered") {
    return <span className={AMOUNT + " leading-none"}>Free</span>
  }
  if (model.state !== "finite" || model.remainingCRD === null) return null
  const total = model.allowanceCRD === null ? null : amountNumber(model.allowanceCRD)
  return (
    <>
      <span
        className={AMOUNT}
        {...(usdLeft === null ? {} : { title: usdLeft, "aria-label": usdLeft })}
      >
        {amountNumber(model.remainingCRD)}
      </span>
      {total !== null && <span className={TOTAL}>/ {total}</span>}
      <span className={UNIT}>CRD</span>
    </>
  )
}

interface FundsBarInput {
  providerName: string
  model: CreditCardModel
  percent: number | null
  label: string | null
  useSharedBar: boolean
}

/**
 * The funds bar line of one rail; a finite percent is required.
 *
 * With the shared flag, the bar takes one full-width line through the shared
 * bar, and the percentage text sits below the bar in its own line. Without the
 * flag, a small Credits title sits above the shared bar with the percentage
 * at its right.
 */
function fundsBar(input: FundsBarInput): ReactNode {
  const { providerName, model, percent, label, useSharedBar } = input
  const remaining = model.remainingCRD
  if (percent === null || label === null || remaining === null) return null
  const valueText = label + " remaining, " + formatCRDAmount(remaining) + " left"
  if (useSharedBar) {
    return (
      <>
        <RemainingBar
          percentRemaining={percent}
          label={providerName + " credit units remaining"}
          valueText={valueText}
        />
        <div className="flex justify-end">
          <span className="tnum text-[18px] font-semibold text-[var(--text-strong)]">
            {label}
          </span>
        </div>
      </>
    )
  }
  return (
    <div className="space-y-0.5">
      <div className="text-[12px] text-[var(--text-strong)]">Credits</div>
      <RemainingBar
        percentRemaining={percent}
        label={providerName + " credit units remaining"}
        valueText={valueText}
        showPercent
      />
    </div>
  )
}

/**
 * The funds bar of one native Credits rail through the shared bar.
 *
 * The fraction carries the native Credit values, so the accessible name and
 * the value text state the Credits amount itself. The percentages come from
 * the exact native strings through the shared helper. The bar keeps one
 * titled line with the percentage at its right through showPercent.
 */
function nativeFundsBar(
  providerName: string,
  credits: TavilyCreditsDisplay,
  percent: number,
): ReactNode {
  if (credits.remaining === null) return null
  const valueNumber = formatCreditValue(credits.remaining)
  if (valueNumber === null) return null
  const label = providerName + " native Credits remaining"
  const valueText =
    valueNumber +
    (credits.allowance === null
      ? " Tavily Credits left"
      : " of " + formatCreditValue(credits.allowance) + " Tavily Credits left")
  return (
    <div className="space-y-0.5">
      <div className="text-[12px] text-[var(--text-strong)]">Credits</div>
      <RemainingBar
        percentRemaining={percent}
        label={label}
        valueText={valueText}
        showPercent
      />
    </div>
  )
}

/** Amount-only fallback of one authoritative OAuth balance: "$24.87 (24870 CRD)", no bar, no percent. */
function balanceFallbackValue(
  usd: string,
  crd: string | null,
  allowance: string | null,
  usdLeft: string | null,
): ReactNode {
  if (crd !== null && allowance !== null) {
    const total = amountNumber(allowance)
    return (
      <>
        <span
          className={AMOUNT}
          {...(usdLeft === null ? {} : { title: usdLeft, "aria-label": usdLeft })}
        >
          {amountNumber(crd)}
        </span>
        <span className={TOTAL}>/ {total}</span>
        <span className={UNIT}>CRD</span>
      </>
    )
  }
  if (crd === null) return <span className={AMOUNT}>{dollarText(usd)}</span>
  return <span className={AMOUNT}>{dollarText(usd) + " (" + formatCRDAmount(crd) + ")"}</span>
}

/** A usable fallback balance: a finite non-empty decimal string. */
function usableFallbackBalance(value: string | null | undefined): string | null {
  if (value === null || value === undefined) return null
  const text = value.trim()
  if (text === "") return null
  return Number.isFinite(Number(text)) ? value : null
}

interface FallbackBalance { usd: string; crd: string | null; allowance: string | null }

/**
 * Amount-only OAuth balance of one card: the limits model holds no funds, so
 * the authoritative remaining shows with its CRD equivalent. An unmetered rail
 * keeps Free; the fallback never overrides it. Null when unusable. A
 * display-only allowance (Parallel $5/mo free credit, You.com $100 signup
 * 100000 CRD total) rides along for the fraction, bar, and capped percent;
 * it never invents backend funds.
 */
function fallbackBalanceOf(
  model: CreditCardModel,
  usd: string | null | undefined,
  crd: string | null | undefined,
  allowance: string | null | undefined,
): FallbackBalance | null {
  if (model.remainingCRD !== null || model.state === "unmetered") return null
  const fallbackUSD = usableFallbackBalance(usd)
  if (fallbackUSD === null) return null
  return { usd: fallbackUSD, crd: usableFallbackBalance(crd), allowance: usableFallbackBalance(allowance) }
}

/**
 * The funds bar of one fallback balance with a display-only allowance (e.g.
 * Parallel 24870/5000 CRD, You.com 4750/100000 CRD). Mirrors the finite funds
 * bar: a finite percent is required, and the bar caps at 100 when remaining
 * exceeds the allowance (Firecrawl 4761.4/3800 pattern). Null without both
 * CRD amounts or a finite percent.
 */
interface FallbackFundsBarInput {
  providerName: string
  fallback: FallbackBalance
  percent: number | null
  label: string | null
  useSharedBar: boolean
}

function fallbackFundsBar(input: FallbackFundsBarInput): ReactNode {
  const { providerName, fallback, percent, label, useSharedBar } = input
  if (percent === null || label === null || fallback.crd === null || fallback.allowance === null) {
    return null
  }
  const valueText = label + " remaining, " + formatCRDAmount(fallback.crd) + " left"
  if (useSharedBar) {
    return (
      <>
        <RemainingBar
          percentRemaining={percent}
          label={providerName + " credit units remaining"}
          valueText={valueText}
        />
        <div className="flex justify-end">
          <span className="tnum text-[18px] font-semibold text-[var(--text-strong)]">
            {label}
          </span>
        </div>
      </>
    )
  }
  return (
    <div className="space-y-0.5">
      <div className="text-[12px] text-[var(--text-strong)]">Credits</div>
      <RemainingBar
        percentRemaining={percent}
        label={providerName + " credit units remaining"}
        valueText={valueText}
        showPercent
      />
    </div>
  )
}

/** The visible value line of one native Credits rail: the fraction or its honest state. */
function nativeCreditValue(credits: TavilyCreditsDisplay): ReactNode {
  if (credits.state === "keyless") {
    return <span className={VALUE}>Keyless access (no Credits quota is reported)</span>
  }
  if (credits.state === "unavailable") {
    return <span className={VALUE}>Transport unavailable</span>
  }
  const total = credits.allowance === null ? null : formatCreditValue(credits.allowance)
  if (credits.remaining === null) {
    if (total === null) return null
    return (
      <>
        <span className={TOTAL}>{"/ " + total}</span>
        <span className={UNIT}>Tavily Credits</span>
      </>
    )
  }
  return (
    <>
      <span className={AMOUNT}>{formatCreditValue(credits.remaining)}</span>
      {total !== null && <span className={TOTAL}>{"/ " + total}</span>}
      <span className={UNIT}>Tavily Credits</span>
    </>
  )
}

/** The footnote facts of one native Credits rail, in the shown order. */
function nativeFootnotes(credits: TavilyCreditsDisplay): ReactNode[] {
  const notes: ReactNode[] = []
  if (credits.state === "paygo") {
    notes.push(
      <Footnote key="paygo">
        Free Credits are spent; further use continues under pay-as-you-go.
      </Footnote>
    )
  }
  if (credits.stale) {
    notes.push(<Footnote key="stale">The last vendor read is stale.</Footnote>)
  }
  if (credits.localCap !== null) {
    notes.push(
      <Footnote key="cap">Local grant ceiling {formatCRDAmount(credits.localCap)}.</Footnote>
    )
  }
  if (credits.remaining !== null && credits.allowance === null) {
    notes.push(
      <Footnote key="allowance">No allowance is reported, so this card shows no percentage.</Footnote>
    )
  }
  return notes
}

/** The whole summary of one rail with native display facts. */
function nativeSummary(
  input: ProviderCreditSummaryProps & { credits: TavilyCreditsDisplay },
): ReactNode {
  const { providerName, credits, actions, info, bodyNotes, fundsControl, rateBars } = input
  const percent = percentRemaining(credits.remaining, credits.allowance)
  return (
    <div className="flex flex-1 flex-col justify-between gap-3">
      <div className="space-y-2">
        {fundsControl}
        {percent !== null && nativeFundsBar(providerName, credits, percent)}
        {rateBars}
      </div>
      {bodyNotes}
      {nativeFootnotes(credits)}
      <div className={`${CREDIT_ROW} mt-auto`}>
        {actions}
        <span className={CREDIT_VALUE}>
          {nativeCreditValue(credits)}
          {info}
        </span>
      </div>
    </div>
  )
}

/**
 * One credit bar with the percent at its right, then the credit row.
 *
 * With `useSharedBar`, the funds bar of a finite rail moves to its own
 * full-width line through the shared bar, and the percentage text sits below
 * that bar in its own line. Without the flag, a Credits title sits above the
 * shared bar with the percentage at its right.
 *
 * The credit row holds the actions at the leading edge and the credit fraction
 * at the trailing edge. The fraction states the remaining amount over the total
 * amount in credit units, and it carries the USD value of the remaining amount
 * as hover text. Only the funds left appear here; the priced use stays a model
 * fact without a row, and the call cost, the call count, the rate limit, the
 * last sync time, and the usage page sit in the info control.
 *
 * The bar appears only with a known positive allowance. A known balance without
 * a denominator keeps its amount and shows no percentage, an unmetered rail
 * shows Free without a fake funds bar. The credit row stays for every state,
 * so the actions of the card always hold one home.
 *
 * A rail with native display facts shows its Credits fraction instead: the bar
 * rides the shared bar with the native percent, the USD hover stays outside the
 * card, and the unknown, keyless, stale, PAYGO, and local-cap facts state
 * themselves in quiet footnotes. Card behavior without the facts stays
 * unchanged.
 */
export function ProviderCreditSummary({
  providerName,
  model,
  credits,
  actions,
  info,
  bodyNotes,
  useSharedBar = false,
  fundsControl,
  rateBars,
  balanceFallbackUSD,
  balanceFallbackCRD,
  balanceFallbackAllowanceCRD,
}: ProviderCreditSummaryProps): ReactNode {
  if (credits !== undefined) {
    return nativeSummary({ providerName, model, credits, actions, info, bodyNotes, fundsControl, rateBars })
  }
  const percent = model.state === "finite" ? model.percentRemaining : null
  const label = percent === null ? null : percentLabel(percent)
  const usdLeft = model.remainingUSD === null ? null : dollarText(model.remainingUSD) + " left"
  // OAuth balance fallback: amount-only without an allowance, or the fraction
  // with a capped bar and percent against a display-only allowance (Parallel
  // $5/mo free credit, You.com $100 signup 100000 CRD total). The allowance
  // is frontend-only, never backend funds.
  const fallback = fallbackBalanceOf(model, balanceFallbackUSD, balanceFallbackCRD, balanceFallbackAllowanceCRD)
  const fallbackPercent =
    fallback?.crd == null || fallback?.allowance == null
      ? null
      : percentRemaining(fallback.crd, fallback.allowance)
  const fallbackLabel = fallbackPercent === null ? null : percentLabel(fallbackPercent)
  const fallbackUsdLeft = fallback === null ? null : dollarText(fallback.usd) + " left"
  return (
    <div className="flex flex-1 flex-col justify-between gap-3">
      <div className="space-y-2">
        {fundsBar({ providerName, model, percent, label, useSharedBar })}
        {fallback !== null &&
          fallbackFundsBar({ providerName, fallback, percent: fallbackPercent, label: fallbackLabel, useSharedBar })}
        {rateBars}
      </div>
      {model.state === "finite" && model.allowanceCRD === null && (
        <Footnote>No allowance is reported, so this card shows no percentage.</Footnote>
      )}
      {fallback !== null && fallback.allowance === null && (
        <Footnote>No allowance is reported, so this card shows no percentage.</Footnote>
      )}
      {bodyNotes}
      <div className={`${CREDIT_ROW} mt-auto`}>
        {actions}
        <span className={CREDIT_VALUE}>
          {fallback !== null
            ? balanceFallbackValue(fallback.usd, fallback.crd, fallback.allowance, fallbackUsdLeft)
            : creditValue(model, usdLeft)}
          {info}
        </span>
      </div>
    </div>
  )
}
