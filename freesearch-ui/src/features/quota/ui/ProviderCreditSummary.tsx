import type { ReactNode } from "react"
import { RemainingBar, percentLabel } from "@/shared/ui/RemainingBar"
import { dollarText, percentRemaining } from "../model/crdDisplay"
import type { CreditCardModel } from "../model/crdCardModel"
import type { NativePool } from "@/domains/dashboard"
import { groupDigits, nativeLeftText } from "../model/numberText"
import { formatCreditValue, type TavilyCreditsDisplay } from "../model/tavilyCredits"
import { Footnote } from "./Footnote"
import { multiplyDecimal } from "../model/manualQuotaMath"

export interface ProviderCreditSummaryProps {
  providerName: string
  model: CreditCardModel
  /**
   * Optional native display facts of one rail. The Tavily card passes its
   * Credits facts here; every other card leaves them absent and keeps the
   * current CRD fraction unchanged.
   */
  credits?: TavilyCreditsDisplay
  nativePool?: NativePool | null
  /** The footer controls that sit at the leading edge of the credit row. */
  actions?: ReactNode
  /** The info control that sits beside the credit fraction. */
  info?: ReactNode
  /** Optional notes rendered before the footer row. */
  bodyNotes?: ReactNode
  /** Optional control row rendered before the funds bar. */
  fundsControl?: ReactNode
  /** Rate progress bars rendered below the funds bar. */
  rateBars?: ReactNode
  /** The one quiet line of a card that knows no funds, no rate, and no balance. */
  emptyText?: string | null
  /**
   * Authoritative OAuth balance fallback (raw USD decimal, e.g. Parallel
   * Account-API remaining or You.com cents-balance remaining). Shown
   * amount-only when the limits model holds no funds; with a display-only
   * allowance it shows a fraction and bar instead.
   */
  balanceFallbackUSD?: string | null
  /** CRD equivalent of the fallback balance, shown as hover text. */
  balanceFallbackCRD?: string | null
  /** Amount-only headline when no fraction is honest: "$192.33 left", "1,320 credits left". */
  amountText?: string | null
  /** A quiet note beside the amount, such as credits above the plan allowance. */
  amountNote?: string | null
}

const AMOUNT = "tnum text-[16px] font-medium text-[var(--text-strong)]"
const TOTAL = "tnum text-[16px] font-medium text-[var(--muted)]"
/** The unit keeps the size of the two amounts, with the quiet color. */
const UNIT = "text-[16px] font-medium text-[var(--muted)]"
const CREDIT_ROW = "mt-auto flex w-full flex-wrap items-center justify-between gap-3"
const CREDIT_VALUE = "ml-auto inline-flex h-8 shrink-0 items-center gap-1.5 leading-none"
const BODY = "flex flex-1 flex-col gap-4"
const EMPTY = "text-[13px] text-[var(--muted)]"

interface FractionInput {
  remaining: string
  total: string | null
  unit: string
  hover: string | null
}

/** The remaining amount, the total once, and the unit once: "4500 / 5000 CRD". */
function fraction({ remaining, total, unit, hover }: FractionInput): ReactNode {
  return (
    <>
      <span className={AMOUNT} {...(hover === null ? {} : { title: hover, "aria-label": hover })}>
        {remaining}
      </span>
      {total !== null && <span className={TOTAL}>/ {total}</span>}
      <span className={UNIT}>{unit}</span>
    </>
  )
}

/**
 * The credit amount of one rail: the fraction, an amount-only headline when
 * no fraction is honest, or Free for an unmetered rail.
 */
function nativePoolValue(pool: NativePool | null): ReactNode {
  if (pool !== null && pool.remaining !== null && ["CREDIT", "REQUEST"].includes(pool.native_unit.toUpperCase())) {
    const unit = pool.native_unit.toUpperCase() === "CREDIT" ? "credits" : "requests"
    return fraction({
      remaining: groupDigits(pool.remaining.replace(/\.0+$/, "")),
      total: pool.allowance === null ? null : groupDigits(pool.allowance.replace(/\.0+$/, "")),
      unit,
      hover: null,
    })
  }
  return null
}

function creditValue(model: CreditCardModel, usdLeft: string | null, amountText: string | null, pool: NativePool | null): ReactNode {
  if (model.state !== "finite" || model.remainingCRD === null) return null
  if (amountText !== null) {
    return (
      <span className={AMOUNT} {...(usdLeft === null ? {} : { title: usdLeft })}>
        {amountText}
      </span>
    )
  }
  const native = nativePoolValue(pool)
  if (native !== null) return native
  const remaining = model.remainingUSD ?? multiplyDecimal(model.remainingCRD, "0.001")
  const total = model.allowanceCRD === null ? null : multiplyDecimal(model.allowanceCRD, "0.001")
  if (remaining === null) return null
  return fraction({ remaining: dollarText(remaining), total: total === null ? null : dollarText(total), unit: "USD", hover: usdLeft })
}

interface FundsBarInput {
  label: string
  percent: number | null
  valueText: string
}

/**
 * The one funds bar of every card: a "Credits left" title, the shared bar,
 * and a quiet percent at its right, so the fraction stays the one prominent
 * figure of the card.
 */
function fundsBar({ label, percent, valueText }: FundsBarInput): ReactNode {
  if (percent === null) return null
  return (
    <div className="space-y-1">
      <div className="text-[12px] text-[var(--text-strong)]">Balance left</div>
      <div className="flex items-center gap-3">
        <div className="min-w-0 flex-1">
          <RemainingBar percentRemaining={percent} label={label} valueText={valueText} />
        </div>
        <span className="tnum shrink-0 text-[12px] text-[var(--muted)]">{percentLabel(percent)}</span>
      </div>
    </div>
  )
}

/** The value text of one CRD funds bar. */
function crdValueText(percent: number | null, remaining: string | null): string {
  if (percent === null || remaining === null) return ""
  const usd = multiplyDecimal(remaining, "0.001")
  return usd === null ? "" : percentLabel(percent) + " remaining, " + dollarText(usd) + " left"
}

function fundsValueText(model: CreditCardModel, pool: NativePool | null): string {
  if (model.percentRemaining === null) return ""
  const native = pool?.remaining == null ? null : nativeLeftText(pool.remaining, pool.native_unit)
  return native === null
    ? crdValueText(model.percentRemaining, model.remainingCRD)
    : percentLabel(model.percentRemaining) + " remaining, " + native
}

/** The visible value line of one native Credits rail. */
function nativeCreditValue(credits: TavilyCreditsDisplay): ReactNode {
  if (credits.state === "keyless") return null
  if (credits.state === "unavailable") {
    return <span className="text-[13px] text-[var(--muted)]">Provider unavailable right now</span>
  }
  const totalRaw = credits.allowance === null ? null : formatCreditValue(credits.allowance)
  const total = totalRaw === null ? null : groupDigits(totalRaw)
  if (credits.remaining === null) {
    if (total === null) return null
    return (
      <>
        <span className={TOTAL}>{"/ " + total}</span>
        <span className={UNIT}>Tavily credits</span>
      </>
    )
  }
  const remaining = groupDigits(formatCreditValue(credits.remaining) ?? credits.remaining)
  return fraction({ remaining, total, unit: "Tavily credits", hover: null })
}

/** The quiet facts of one native Credits rail, in the shown order. */
function nativeFootnotes(credits: TavilyCreditsDisplay): ReactNode[] {
  const notes: ReactNode[] = []
  if (credits.state === "paygo") {
    notes.push(<Footnote key="paygo">Free credits are used up, so further use is billed as you go</Footnote>)
  }
  if (credits.stale) notes.push(<Footnote key="stale">The last provider reading is out of date</Footnote>)
  if (credits.localCap !== null) {
    notes.push(<Footnote key="cap">Budget limit {dollarText(multiplyDecimal(credits.localCap, "0.001") ?? "0")}</Footnote>)
  }
  return notes
}

/** The native Credits bar of one Tavily rail. */
function nativeFundsBar(providerName: string, credits: TavilyCreditsDisplay): ReactNode {
  const percent = percentRemaining(credits.remaining, credits.allowance)
  if (percent === null || credits.remaining === null) return null
  const valueNumber = formatCreditValue(credits.remaining)
  if (valueNumber === null) return null
  const valueText =
    valueNumber +
    (credits.allowance === null
      ? " Tavily credits left"
      : " of " + groupDigits(formatCreditValue(credits.allowance) ?? credits.allowance) + " Tavily credits left")
  return fundsBar({ label: providerName + " native Credits remaining", percent, valueText })
}

/** The whole summary of one rail with native display facts. */
function nativeSummary(input: ProviderCreditSummaryProps & { credits: TavilyCreditsDisplay }): ReactNode {
  const { providerName, credits, actions, info, bodyNotes, fundsControl, rateBars, emptyText } = input
  return (
    <div className={BODY}>
      <div className="space-y-3">
        {fundsControl}
        {nativeFundsBar(providerName, credits)}
        {rateBars}
        {emptyText != null && <p className={EMPTY}>{emptyText}</p>}
      </div>
      {bodyNotes}
      {nativeFootnotes(credits)}
      <div className={CREDIT_ROW}>
        {actions}
        <span className={CREDIT_VALUE}>
          {nativeCreditValue(credits)}
          {info}
        </span>
      </div>
    </div>
  )
}

/** A usable fallback balance: a finite non-empty decimal string. */
function usable(value: string | null | undefined): string | null {
  if (value === null || value === undefined) return null
  const text = value.trim()
  if (text === "") return null
  return Number.isFinite(Number(text)) ? value : null
}

interface FallbackBalance { usd: string; crd: string | null }

/**
 * Amount-only OAuth balance of one card: the limits model holds no funds, so
 * the authoritative remaining shows with its CRD equivalent. An unmetered rail
 * keeps Free; the fallback never overrides it.
 */
function fallbackBalanceOf(model: CreditCardModel, input: ProviderCreditSummaryProps): FallbackBalance | null {
  if (model.remainingCRD !== null || model.state === "unmetered") return null
  const usd = usable(input.balanceFallbackUSD)
  if (usd === null) return null
  return { usd, crd: usable(input.balanceFallbackCRD) }
}

/** The value of one fallback balance: the dollar amount left, with its CRD value as hover text. */
function fallbackValue(fallback: FallbackBalance): ReactNode {
  const amount = nativeLeftText(fallback.usd, "USD") ?? dollarText(fallback.usd) + " left"
  const hover = fallback.crd === null ? null : dollarText(multiplyDecimal(fallback.crd, "0.001") ?? "0")
  return (
    <span className={AMOUNT} {...(hover === null ? {} : { title: hover })}>
      {amount}
    </span>
  )
}

/**
 * The funds block of one card: the funds bar, the rate bars, and the footer
 * row with the card controls at the leading edge and the credit fraction at
 * the trailing edge.
 *
 * Every card draws the same bar block: a Credits title, the shared bar, and
 * the percent at its right. The bar appears only with a known positive
 * allowance. A known balance without an allowance keeps its amount with no
 * bar, and an unmetered rail shows Free. A card that knows nothing shows one
 * quiet line instead. The fraction carries the USD value as hover text.
 */
export function ProviderCreditSummary(props: ProviderCreditSummaryProps): ReactNode {
  const { providerName, model, credits, actions, info, bodyNotes, fundsControl, rateBars, emptyText } = props
  if (credits !== undefined) return nativeSummary({ ...props, credits })
  const percent = model.state === "finite" ? model.percentRemaining : null
  const usdLeft = model.remainingUSD === null ? null : dollarText(model.remainingUSD) + " left"
  const fallback = fallbackBalanceOf(model, props)
  const barLabel = providerName + " balance remaining"
  return (
    <div className={BODY}>
      <div className="space-y-3">
        {fundsControl}
        {fundsBar({ label: barLabel, percent, valueText: fundsValueText(model, props.nativePool ?? null) })}
        {rateBars}
        {emptyText != null && <p className={EMPTY}>{emptyText}</p>}
      </div>
      {props.amountNote != null && <Footnote>{props.amountNote}</Footnote>}
      {bodyNotes}
      <div className={CREDIT_ROW}>
        {actions}
        <span className={CREDIT_VALUE}>
          {fallback !== null ? fallbackValue(fallback) : creditValue(model, usdLeft, props.amountText ?? null, props.nativePool ?? null)}
          {info}
        </span>
      </div>
    </div>
  )
}
