import type { ReactNode } from "react"
import { RemainingBar, percentLabel } from "@/shared/ui/RemainingBar"
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
  /** Rate progress bars rendered above the action row. */
  rateBars?: ReactNode
}

const AMOUNT = "tnum text-[18px] font-semibold text-[var(--text-strong)]"
const TOTAL = "tnum text-[18px] font-semibold text-[var(--muted)]"
/** The unit keeps the size of the two amounts, with the quiet color. */
const UNIT = "text-[18px] font-semibold text-[var(--muted)]"
const CRD_SUFFIX = " CRD"
const CREDIT_ROW = "flex w-full flex-wrap items-center justify-between gap-3"
const CREDIT_VALUE = "inline-flex h-8 items-center gap-1.5 leading-none"

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
 */
export function ProviderCreditSummary({
  providerName,
  model,
  actions,
  info,
  useSharedBar = false,
  rateBars,
}: ProviderCreditSummaryProps): ReactNode {
  const percent = model.state === "finite" ? model.percentRemaining : null
  const label = percent === null ? null : percentLabel(percent)
  const usdLeft = model.remainingUSD === null ? null : dollarText(model.remainingUSD) + " left"
  return (
    <div className="flex flex-1 flex-col justify-between gap-3">
      <div className="space-y-2">
        {fundsBar({ providerName, model, percent, label, useSharedBar })}
        {rateBars}
      </div>
      <div className={`${CREDIT_ROW} mt-auto`}>
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
