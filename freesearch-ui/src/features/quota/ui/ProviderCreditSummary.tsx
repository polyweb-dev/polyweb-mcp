import type { ReactNode } from "react"
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
}

const VALUE = "tnum text-[15px] text-[var(--text-strong)]"
const AMOUNT = "tnum text-[18px] font-semibold text-[var(--text-strong)]"
const TOTAL = "tnum text-[18px] font-semibold text-[var(--muted)]"
/** The unit keeps the size of the two amounts, with the quiet color. */
const UNIT = "text-[18px] font-semibold text-[var(--muted)]"
const CRD_SUFFIX = " CRD"
const CREDIT_ROW = "flex w-full flex-wrap items-center justify-between gap-3"
const CREDIT_VALUE = "flex items-center gap-1.5"
const BAR = "h-2 min-w-0 flex-1 overflow-hidden rounded-full bg-[var(--border-subtle)]"
const FILL = "h-full rounded-full bg-[var(--signal)]"
const PERCENT = "tnum shrink-0 text-[18px] font-semibold text-[var(--text-strong)]"

/** One decimal digit at most, and no trailing ".0". */
function percentLabel(percent: number): string {
  return (percent % 1 === 0 ? percent.toFixed(0) : percent.toFixed(1)) + "%"
}

/** The progress bar of one rail with the percent at its right. */
function creditBar(
  label: string,
  ariaLabel: string,
  percent: number,
  valueText: string | null,
): ReactNode {
  return (
    <div className="flex items-center gap-3">
      <div
        className={BAR}
        role="progressbar"
        aria-label={ariaLabel}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={percent}
        aria-valuetext={valueText === null ? undefined : valueText}
      >
        <div className={FILL} style={{ width: percent + "%" }} />
      </div>
      <span className={PERCENT}>{label}</span>
    </div>
  )
}

/** The number part of one shown credit amount: "4500 CRD" becomes "4500". */
function amountNumber(amount: string): string {
  const text = formatCRDAmount(amount)
  return text.endsWith(CRD_SUFFIX) ? text.slice(0, -CRD_SUFFIX.length) : text
}

/** The bar text of one rail; the bar appears only with a known remaining value. */
function barFacts(
  remaining: string | null,
  percent: number,
  ariaLabel: string,
): ReactNode | null {
  if (remaining === null) return null
  const value = formatCreditValue(remaining)
  if (value === null) return null
  return creditBar(
    percentLabel(percent),
    ariaLabel,
    percent,
    percentLabel(percent) + " remaining, " + value + " Credits left",
  )
}

/** The credit amount of one rail: the fraction, the plain amount, or the state text. */
function creditValue(model: CreditCardModel, usdLeft: string | null): ReactNode {
  if (model.state === "unmetered") return <span className={VALUE}>Free - unmetered</span>
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
        <span className={UNIT}>{credits.unit}</span>
      </>
    )
  }
  return (
    <>
      <span className={AMOUNT}>{formatCreditValue(credits.remaining)}</span>
      {total !== null && <span className={TOTAL}>{"/ " + total}</span>}
      <span className={UNIT}>{credits.unit}</span>
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
  providerName: string,
  credits: TavilyCreditsDisplay,
  actions: ReactNode | undefined,
  info: ReactNode | undefined,
): ReactNode {
  const percent = percentRemaining(credits.remaining, credits.allowance)
  const ariaLabel = providerName + " native Credits remaining"
  return (
    <div className="space-y-2">
      {percent !== null && barFacts(credits.remaining, percent, ariaLabel)}
      <div className={CREDIT_ROW}>
        {actions}
        <span className={CREDIT_VALUE}>
          {nativeCreditValue(credits)}
          {info}
        </span>
      </div>
      {nativeFootnotes(credits)}
    </div>
  )
}

/**
 * One credit bar with the percent at its right, then the credit row.
 *
 * The credit row holds the actions at the leading edge and the credit fraction
 * at the trailing edge. The fraction states the remaining amount over the total
 * amount in credit units, and it carries the USD value of the remaining amount
 * as hover text. Only the funds left appear here; the priced use stays a model
 * fact without a row, and the call cost, the call count, the rate limit, the
 * last sync time, and the usage page sit in the info control.
 *
 * The bar appears only with a known positive allowance. A known balance without
 * a denominator keeps its amount and shows no percentage, and an unmetered rail
 * shows its state without a fake bar. The credit row stays for every state, so
 * the actions of the card always hold one home.
 *
 * A rail with native display facts shows its Credits fraction instead: the bar
 * carries the native percent, the USD hover text stays outside the card, and
 * the unknown, keyless, stale, PAYGO, and local-cap facts state themselves in
 * quiet footnotes. Card behavior without the facts stays unchanged.
 */
export function ProviderCreditSummary({
  providerName,
  model,
  credits,
  actions,
  info,
}: ProviderCreditSummaryProps): ReactNode {
  if (credits !== undefined) return nativeSummary(providerName, credits, actions, info)
  const percent = model.state === "finite" ? model.percentRemaining : null
  const label = percent === null ? null : percentLabel(percent)
  const usdLeft = model.remainingUSD === null ? null : dollarText(model.remainingUSD) + " left"
  const ariaLabel = providerName + " credit units remaining"
  return (
    <div className="space-y-2">
      {percent !== null && label !== null && model.remainingCRD !== null && (
        <div className="flex items-center gap-3">
          <div
            className={BAR}
            role="progressbar"
            aria-label={ariaLabel}
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={percent}
            aria-valuetext={label + " remaining, " + formatCRDAmount(model.remainingCRD) + " left"}
          >
            <div className={FILL} style={{ width: percent + "%" }} />
          </div>
          <span className={PERCENT}>{label}</span>
        </div>
      )}
      <div className={CREDIT_ROW}>
        {actions}
        <span className={CREDIT_VALUE}>
          {creditValue(model, usdLeft)}
          {info}
        </span>
      </div>
      {model.state === "finite" && model.allowanceCRD === null && (
        <Footnote>No allowance is reported, so this card shows no percentage.</Footnote>
      )}
    </div>
  )
}
