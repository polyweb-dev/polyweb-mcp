import { useState } from "react"
import type { ReactNode } from "react"
import { Info } from "lucide-react"
import type { ProviderAuthLimits } from "@/domains/dashboard"
import { Button } from "@/shared/ui/button"
import { formatDateTime, formatRelativeTime } from "@/shared/lib/formatTime"
import { Popover, PopoverContent, PopoverTitle, PopoverTrigger } from "@/shared/ui/popover"
import type { ProviderInfo, ProviderInfoFact } from "../model/providerInfo"
import type { TavilyDisplayAdapter } from "../model/tavilyCredits"
import { ProviderLimitsDetail } from "./ProviderLimitsDetail"
import { ProviderTierBars } from "./ProviderTierBars"

export interface ProviderInfoPopoverProps {
  providerId: string
  providerName: string
  info: ProviderInfo
  auth: ProviderAuthLimits
  /**
   * The native display inputs of one Tavily rail. They stay inside this
   * disclosure: Tavily USD rows and Credits local caps appear here only, so a
   * closed popover shows no vendor USD outside it.
   */
  nativeDisplay?: TavilyDisplayAdapter
}

const ROW = "grid w-full grid-cols-[fit-content(45%)_minmax(0,1fr)] items-baseline gap-x-3 border-b border-[var(--border-subtle)] py-2 last:border-0"
const HEAD = "grid w-full grid-cols-[minmax(0,1fr)_auto] items-baseline gap-3 border-b border-[var(--border-subtle)] pb-2"
/** The header note and every fact row keep the one size of the body text. */
const FACT = "text-[12px]"
const LABEL = FACT + " min-w-0 break-words text-[var(--muted)]"
const VALUE = FACT + " tnum min-w-0 break-words text-[var(--text-strong)]"
const NOTE = FACT + " min-w-0 break-words text-[var(--muted)]"
const TITLE = FACT + " font-semibold"
/** The icon matches the shown size of the credit fraction. */
const ICON = "size-[18px]"
const DETAIL_EDGE = "border-t border-[var(--border-subtle)] pt-2"

/** One row: the quiet label at the leading edge and the value at the trailing edge. */
function infoRow(fact: ProviderInfoFact): ReactNode {
  const timestamp = fact.label === "Last sync" ? Date.parse(fact.value) : NaN
  const value = Number.isFinite(timestamp)
    ? <time className={VALUE} dateTime={fact.value} title={formatDateTime(fact.value)}>{formatRelativeTime(timestamp, Date.now())}</time>
    : <span className={VALUE}>{fact.value}</span>
  const note = fact.note === null ? null : <span className={NOTE}>{fact.note}</span>
  return (
    <div key={fact.label} className={ROW}>
      <span className={LABEL}>{fact.label}</span>
      <span className="flex min-w-0 flex-wrap items-baseline justify-end gap-x-1.5 text-right">
        {value}
        {note}
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
      </a>
    </div>
  )
}


/**
 * The remaining detail of one rail: the known tier facts and the vendor rows
 * that no other surface states. Each part carries its own top edge, so an
 * absent part leaves no empty divider. The native display of a Tavily rail
 * stays inside the disclosure with the vendor detail. The rate bars moved to
 * the card body, so this disclosure states no second copy of them.
 */
function vendorDetail(
  providerName: string,
  auth: ProviderAuthLimits,
  nativeDisplay: TavilyDisplayAdapter | undefined,
): ReactNode {
  return (
    <>
      <ProviderTierBars providerName={providerName} freeTiers={auth.free_tiers}
        paidTiers={auth.paid_tiers} tierSplitKnown={auth.tier_split_known}
        {...(nativeDisplay !== undefined ? { nativeDisplay } : {})} />
      <ProviderLimitsDetail
        providerName={providerName}
        auth={auth}
        layout="popover"
        {...(nativeDisplay !== undefined ? { nativeDisplay } : {})}
      />
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
 *
 * For the keyless rail of `keenable`, the header credit note carries the word
 * `free`, and the two Usd cost rows keep their labels while their value and
 * note sit inside a strike with the word `free` beside them.
 */
export function ProviderInfoPopover({
  providerId,
  providerName,
  info,
  auth,
  nativeDisplay,
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
        <PopoverContent
          side="bottom" align="start"
          className="w-[min(26rem,calc(100vw-2rem))] max-w-[calc(100vw-2rem)] max-h-[calc(100vh-2rem)] space-y-2 overflow-y-auto"
        >
          <div className={HEAD}>
            <PopoverTitle
              render={<span className={TITLE} style={{ color: "var(--text-strong)" }} />}
            >
              Quota details
            </PopoverTitle>
            {info.creditNote !== null && info.creditNote.toLowerCase() !== "free" && (
              <span className={TITLE + " min-w-0 text-right"} style={{ color: "var(--muted)" }}>
                {info.creditNote}
              </span>
            )}
          </div>
          {info.facts.map(infoRow)}
          {vendorDetail(providerName, auth, nativeDisplay)}
          {usageLink(providerName, info.usageUrl)}
        </PopoverContent>
      )}
    </Popover>
  )
}
