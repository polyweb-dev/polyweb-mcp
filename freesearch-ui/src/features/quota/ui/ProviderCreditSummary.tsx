import type { ReactNode } from "react"
import { formatCRDAmount } from "../model/crdDisplay"
import type { CreditCardModel } from "../model/crdCardModel"

export interface ProviderCreditSummaryProps {
  providerName: string
  model: CreditCardModel
}

const LABEL = "text-[12px] text-[var(--muted)]"
const VALUE = "tnum text-[15px] text-[var(--text-strong)]"

/** One decimal digit at most, and no trailing ".0". */
function percentLabel(percent: number): string {
  return (percent % 1 === 0 ? percent.toFixed(0) : percent.toFixed(1)) + "%"
}

/**
 * One credit bar with the percent at its right, then the CRD and USD funds.
 *
 * The bar appears only with a known positive allowance. A known balance
 * without a denominator keeps its amounts and shows no percentage, an unmetered
 * rail shows its state without a fake bar, and an unknown rail shows nothing.
 */
export function ProviderCreditSummary({
  providerName,
  model,
}: ProviderCreditSummaryProps): ReactNode {
  if (model.state === "unmetered") {
    return <p className={VALUE}>Free - unmetered</p>
  }
  if (model.state !== "finite" || model.remainingCRD === null) return null
  const percent = model.percentRemaining
  const label = percent === null ? null : percentLabel(percent)
  return (
    <div className="space-y-2">
      {percent !== null && label !== null && (
        <div className="flex items-center gap-3">
          <div
            className="h-2 min-w-0 flex-1 overflow-hidden rounded-full bg-[var(--border-subtle)]"
            role="progressbar"
            aria-label={providerName + " credit units remaining"}
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={percent}
            aria-valuetext={label + " remaining, " + formatCRDAmount(model.remainingCRD) + " left"}
          >
            <div
              className="h-full rounded-full bg-[var(--signal)]"
              style={{ width: percent + "%" }}
            />
          </div>
          <span className="tnum shrink-0 text-[18px] font-semibold text-[var(--text-strong)]">
            {label}
          </span>
        </div>
      )}
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
        <div>
          <div className={LABEL}>CRD left</div>
          <div className={VALUE}>{formatCRDAmount(model.remainingCRD)}</div>
        </div>
        {model.remainingUSD !== null && (
          <div>
            <div className={LABEL}>USD left</div>
            <div className={VALUE}>{model.remainingUSD}</div>
          </div>
        )}
        {model.pricedUseUSD !== null && (
          <div>
            <div className={LABEL}>USD use (priced)</div>
            <div className={VALUE}>{model.pricedUseUSD}</div>
          </div>
        )}
      </div>
      {model.allowanceCRD === null && (
        <p className={LABEL}>No allowance is reported, so this card shows no percentage.</p>
      )}
    </div>
  )
}
