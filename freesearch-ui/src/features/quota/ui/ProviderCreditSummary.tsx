import type { ReactNode } from "react"
import { RemainingBar } from "@/shared/ui/RemainingBar"
import { dollarText, formatCRDAmount } from "../model/crdDisplay"
import type { CreditCardModel } from "../model/crdCardModel"
import { Footnote } from "./Footnote"

export interface ProviderCreditSummaryProps {
  providerName: string
  model: CreditCardModel
  /** The action row that sits at the leading edge of the credit row. */
  actions?: ReactNode
  /** The info control that sits beside the credit fraction. */
  info?: ReactNode
  /** Draw the funds bar of a finite rail through the shared bar. */
  useSharedBar?: boolean
  /** Strike the prior value of an unmetered rail and put the word free beside it. */
  freeKeyless?: boolean
}

const VALUE = "tnum text-[15px] text-[var(--text-strong)]"
const AMOUNT = "tnum text-[18px] font-semibold text-[var(--text-strong)]"
const TOTAL = "tnum text-[18px] font-semibold text-[var(--muted)]"
/** The unit keeps the size of the two amounts, with the quiet color. */
const UNIT = "text-[18px] font-semibold text-[var(--muted)]"
const CRD_SUFFIX = " CRD"
const CREDIT_ROW = "flex w-full flex-wrap items-center justify-between gap-3"
const CREDIT_VALUE = "flex items-center gap-1.5"

/** One decimal digit at most, and no trailing ".0". */
function percentLabel(percent: number): string {
  return (percent % 1 === 0 ? percent.toFixed(0) : percent.toFixed(1)) + "%"
}

/** The number part of one shown credit amount: "4500 CRD" becomes "4500". */
function amountNumber(amount: string): string {
  const text = formatCRDAmount(amount)
  return text.endsWith(CRD_SUFFIX) ? text.slice(0, -CRD_SUFFIX.length) : text
}

/** The credit amount of one rail: the fraction, the plain amount, or the state text. */
function creditValue(
  model: CreditCardModel,
  usdLeft: string | null,
  freeKeyless: boolean,
): ReactNode {
  if (model.state === "unmetered") {
    const prior = <span className={VALUE}>Free - unmetered</span>
    if (!freeKeyless) return prior
    return (
      <>
        <s>{prior}</s>
        <span className={VALUE}>free</span>
      </>
    )
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
 * flag, the bar keeps its default row with the percentage at the right.
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
    <div className="flex items-center gap-3">
      <div
        className="h-2 min-w-0 flex-1 overflow-hidden rounded-full bg-[var(--border-subtle)]"
        role="progressbar"
        aria-label={providerName + " credit units remaining"}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={percent}
        aria-valuetext={valueText}
      >
        <div className="h-full rounded-full bg-[var(--signal)]" style={{ width: percent + "%" }} />
      </div>
      <span className="tnum shrink-0 text-[18px] font-semibold text-[var(--text-strong)]">
        {label}
      </span>
    </div>
  )
}

/**
 * One credit bar with the percent at its right, then the credit row.
 *
 * With `useSharedBar`, the funds bar of a finite rail moves to its own
 * full-width line through the shared bar, and the percentage text sits below
 * that bar in its own line. Without the flag, the bar keeps its default row.
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
 * With `freeKeyless`, an unmetered rail keeps its prior state text inside a
 * strike element and puts the word `free` beside it. The strike never touches a
 * search or fetch cost, and the flag changes no model data.
 */
export function ProviderCreditSummary({
  providerName,
  model,
  actions,
  info,
  useSharedBar = false,
  freeKeyless = false,
}: ProviderCreditSummaryProps): ReactNode {
  const percent = model.state === "finite" ? model.percentRemaining : null
  const label = percent === null ? null : percentLabel(percent)
  const usdLeft = model.remainingUSD === null ? null : dollarText(model.remainingUSD) + " left"
  return (
    <div className="space-y-2">
      {fundsBar({ providerName, model, percent, label, useSharedBar })}
      <div className={CREDIT_ROW}>
        {actions}
        <span className={CREDIT_VALUE}>
          {creditValue(model, usdLeft, freeKeyless)}
          {info}
        </span>
      </div>
      {model.state === "finite" && model.allowanceCRD === null && (
        <Footnote>No allowance is reported, so this card shows no percentage.</Footnote>
      )}
    </div>
  )
}
