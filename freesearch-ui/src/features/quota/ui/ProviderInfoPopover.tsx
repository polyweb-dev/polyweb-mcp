import { useState } from "react"
import type { ReactNode } from "react"
import { Info } from "lucide-react"
import type { ProviderAuthLimits } from "@/domains/dashboard"
import { Button } from "@/shared/ui/button"
import { Popover, PopoverContent, PopoverTitle, PopoverTrigger } from "@/shared/ui/popover"
import { operationAvailable } from "../model/crdCardModel"
import type { ProviderInfo, ProviderInfoFact } from "../model/providerInfo"
import { ProviderLimitsDetail } from "./ProviderLimitsDetail"
import { ProviderRateBars } from "./ProviderRateBars"
import { ProviderTierBars } from "./ProviderTierBars"

export interface ProviderInfoPopoverProps {
  providerId: string
  providerName: string
  info: ProviderInfo
  auth: ProviderAuthLimits
}

const ROW = "flex w-full items-center justify-between gap-3"
const HEAD = "flex w-full items-center justify-between gap-3 border-b border-[var(--border-subtle)] pb-2"
/** The header note and every fact row keep the one size of the body text. */
const FACT = "text-[12px]"
const LABEL = FACT + " text-[var(--muted)]"
const VALUE = FACT + " tnum text-[var(--text-strong)]"
const NOTE = FACT + " text-[var(--muted)]"
const TITLE = FACT + " font-semibold"
/** The icon matches the shown size of the credit fraction. */
const ICON = "size-[18px]"
const DETAIL_EDGE = "border-t border-[var(--border-subtle)] pt-2"

/** One row: the quiet label at the leading edge, the exact value at the trailing edge. */
function infoRow(fact: ProviderInfoFact): ReactNode {
  return (
    <div key={fact.label} className={ROW}>
      <span className={LABEL}>{fact.label}</span>
      <span className="flex items-baseline gap-1.5">
        <span className={VALUE}>{fact.value}</span>
        {fact.note !== null && <span className={NOTE}>{fact.note}</span>}
      </span>
    </div>
  )
}

/** The usage link of one rail; only an http or https address becomes a link. */
function usageLink(providerName: string, usageUrl: string | null): ReactNode {
  if (usageUrl === null) return null
  return (
    <div className={DETAIL_EDGE}>
      <a
        className="text-[12px] text-[var(--signal)] hover:underline"
        href={usageUrl}
        target="_blank"
        rel="noreferrer noopener"
      >
        {providerName} usage page
        <span aria-hidden="true"> →</span>
      </a>
    </div>
  )
}

/**
 * The remaining detail of one rail: the known tier facts, the known rate bars,
 * and the vendor rows that no other surface states. Each part carries its own
 * top edge, so an absent part leaves no empty divider.
 */
function vendorDetail(providerName: string, auth: ProviderAuthLimits): ReactNode {
  return (
    <>
      <ProviderTierBars providerName={providerName} freeTiers={auth.free_tiers}
        paidTiers={auth.paid_tiers} tierSplitKnown={auth.tier_split_known} />
      <ProviderRateBars providerName={providerName} progress={auth.rate_progress}
        fetchAvailable={operationAvailable(auth, "fetch")} />
      <ProviderLimitsDetail providerName={providerName} auth={auth} />
    </>
  )
}

/**
 * Info control of one card.
 *
 * The icon opens the credit details of its own rail. The surface holds the
 * header row, the fact rows, the usage link, and the vendor detail, so it owns
 * every detail of the card. The button takes focus and the keyboard activates
 * it; the Escape key closes the surface and returns the focus to the button.
 * The surface exists only while it is open, so a closed popover leaves no
 * element behind. An empty fact set yields no icon.
 */
export function ProviderInfoPopover({
  providerId,
  providerName,
  info,
  auth,
}: ProviderInfoPopoverProps): ReactNode {
  const [open, setOpen] = useState(false)
  if (info.facts.length === 0 && info.usageUrl === null) return null
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger
        render={
          <Button
            type="button"
            variant="ghost"
            size="icon-sm"
            className="text-[var(--muted)]"
            data-testid={"credit-info-" + providerId}
            aria-label={"Credit details for " + providerName}
          />
        }
      >
        <Info aria-hidden="true" className={ICON} />
      </PopoverTrigger>
      {open && (
        <PopoverContent className="w-96 space-y-2">
          <div className={HEAD}>
            <PopoverTitle
              render={<span className={TITLE} style={{ color: "var(--text-strong)" }} />}
            >
              Quota Details
            </PopoverTitle>
            {info.creditNote !== null && (
              <span className={TITLE} style={{ color: "var(--muted)" }}>
                {info.creditNote}
              </span>
            )}
          </div>
          {info.facts.map(infoRow)}
          {vendorDetail(providerName, auth)}
          {usageLink(providerName, info.usageUrl)}
        </PopoverContent>
      )}
    </Popover>
  )
}
