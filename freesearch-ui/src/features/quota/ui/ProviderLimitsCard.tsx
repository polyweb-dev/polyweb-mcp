import { useState } from "react"
import type { ReactNode } from "react"
import { Button } from "@/shared/ui/button"
import { ProviderLogo } from "@/shared/ui/ProviderLogo"
import type { ProviderAuthLimits, ProviderLimits } from "@/domains/dashboard"
import { providerCRDModel } from "../model/crdDisplay"
import { useProviderLimits } from "../model/useProviderLimits"
import { CRDGrantForm } from "./CRDGrantForm"
import { LimitHistory } from "./LimitHistory"
import { ProviderLimitsDetail } from "./ProviderLimitsDetail"
import { ProviderRateBars } from "./ProviderRateBars"
import { ProviderTierBars } from "./ProviderTierBars"

export interface ProviderLimitsCardProps {
  providerId: string
  providerName: string
  limits: ProviderLimits
}

const CARD = "space-y-3 rounded-lg border border-[var(--border-subtle)] bg-[var(--surface)] p-4"
const LABEL = "text-[12px] text-[var(--muted)]"
const VALUE = "tnum text-[15px] text-[var(--text-strong)]"
const CHIP = "rounded-full border border-[var(--border-subtle)] bg-[var(--elevated)] px-2 py-0.5 text-[11px] text-[var(--muted)]"

function slug(providerId: string): string {
  return providerId.toLowerCase().replace(/[^a-z0-9]+/g, "-")
}

function activeAuth(data: ProviderLimits): ProviderAuthLimits | undefined {
  return data.auths.find((entry) => entry.auth_mode === data.active_auth_mode) ?? data.auths[0]
}

function canFetch(auth: ProviderAuthLimits): boolean {
  if (auth.fetch === null) return false
  return auth.fetch.supported && auth.fetch.transport_available
}

/** A new stored grant remounts the form, so its draft starts from the server. */
function grantKey(auth: ProviderAuthLimits): string {
  const grants = auth.grants
  if (grants === null) return auth.auth_mode + "-none"
  return auth.auth_mode + "-" + grants.version + "-" + grants.period_start
}

/**
 * One provider credit-unit card.
 *
 * The card owns its expansion state, so a disclosure of one provider never
 * moves another. Credit-unit headlines lead the card; native and USD values
 * stay inside the disclosure.
 */
export function ProviderLimitsCard({
  providerId,
  providerName,
  limits,
}: ProviderLimitsCardProps): ReactNode {
  const controller = useProviderLimits(providerId)
  const [expanded, setExpanded] = useState(false)
  const data = controller.limits ?? limits
  const auth = activeAuth(data)
  if (auth === undefined) {
    return <article className={CARD}>{providerName}: no limit data reported by the backend.</article>
  }

  const model = providerCRDModel({
    provider: data.provider,
    providerName,
    authMode: auth.auth_mode,
    auth,
  })
  const titleId = "limits-title-" + slug(providerId)
  const panelId = "limits-panel-" + slug(providerId)

  return (
    <article aria-labelledby={titleId} className={CARD}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex min-w-0 items-center gap-2">
          <ProviderLogo providerId={providerId} name={providerName} />
          <h4 id={titleId} className="truncate text-[13px] font-semibold text-[var(--text-strong)]">
            {providerName}
          </h4>
          <span className={CHIP}>{auth.auth_mode} rail</span>
        </div>
        <div className="flex items-center gap-2">
          <Button type="button" variant="outline" size="lg" className="px-3"
            disabled={controller.syncing} aria-label={"Sync limits for " + providerName}
            onClick={() => void controller.syncNow()}>
            {controller.syncing ? "Syncing…" : "Sync"}
          </Button>
          <Button type="button" variant="outline" size="lg" className="px-3"
            aria-expanded={expanded} aria-controls={panelId}
            onClick={() => setExpanded((previous) => !previous)}>
            {expanded ? "Hide detail" : "Show detail"}
          </Button>
        </div>
      </div>

      {controller.error !== null && (
        <p role="alert" className="rounded border border-[var(--status-danger)]/40 p-2.5 text-[12px]"
          style={{ color: "var(--status-danger)" }}>
          {controller.error}
        </p>
      )}

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <div>
          <div className={LABEL}>Search credit units left</div>
          <div className={VALUE}>{model.searchHeadline}</div>
        </div>
        <div>
          <div className={LABEL}>Fetch credit units left</div>
          <div className={VALUE}>{model.fetchHeadline}</div>
        </div>
      </div>

      {controller.syncNote !== null && <p role="status" className={LABEL}>{controller.syncNote}</p>}
      {model.sharedNote !== null && <p className={LABEL}>{model.sharedNote}</p>}
      {model.notes.length > 0 && (
        <ul className="space-y-0.5 text-[12px] text-[var(--muted)]">
          {model.notes.map((note) => <li key={note}>{note}</li>)}
        </ul>
      )}

      <ProviderTierBars providerName={providerName} freeTiers={auth.free_tiers}
        paidTiers={auth.paid_tiers} tierSplitKnown={auth.tier_split_known} />
      <ProviderRateBars providerName={providerName} progress={auth.rate_progress} />

      {expanded && (
        <div id={panelId} className="space-y-4 border-t border-[var(--border-subtle)] pt-3">
          <ProviderLimitsDetail providerName={providerName} auth={auth} />
          <CRDGrantForm key={grantKey(auth)} providerName={providerName} authMode={auth.auth_mode}
            grants={auth.grants} fetchAvailable={canFetch(auth)} saving={controller.saving}
            saveError={controller.saveError} staleVersion={controller.staleVersion}
            onSave={controller.saveGrant} onReload={() => void controller.reload()} />
          <LimitHistory providerName={providerName} events={controller.history}
            loading={controller.historyLoading} error={controller.historyError}
            hasMore={controller.hasMoreHistory} onLoadMore={controller.loadMoreHistory} />
        </div>
      )}
    </article>
  )
}
