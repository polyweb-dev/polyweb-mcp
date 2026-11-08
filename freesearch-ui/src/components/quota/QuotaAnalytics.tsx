import type { FC } from "react"
import { useFreeSearch } from "@/context/useFreeSearch"
import { useProjectsOptional } from "@/domains/projects"
import { QuotaPage } from "@/features/quota/ui/QuotaPage"
import { KeyBalances } from "@/features/quota/ui/KeyBalances"
import { listKeyBalances } from "@/features/quota/model/keyBalances"
import type { RateTierSlotArgs } from "@/features/quota/ui/ProviderLimitsCard"
import { isManualQuotaEligible } from "@/features/quota/model/quotaEligibility"
import { useScopedResource } from "@/shared/lib/useScopedResource"
import { TavilyRateTierSelect } from "../settings/TavilyRateTierSelect"

/**
 * Compatibility shell: the usage route keeps rendering QuotaAnalytics while
 * the quota feature owns the page. The Tavily tier control stays composed
 * here, so the quota feature never imports the Settings feature directly.
 * Parallel OAuth no longer pairs from this page: OAuth belongs to one
 * vault key and connects from the Keys and pools page.
 */
export const QuotaAnalytics: FC<{
  manualQuotaEligible?: typeof isManualQuotaEligible
}> = ({ manualQuotaEligible = isManualQuotaEligible }) => {
  const { providers, canEditControls, refreshProviders, refreshDashboard } = useFreeSearch()
  const { accountId } = useProjectsOptional()
  const oauth = useScopedResource({
    scopeKey: `quota:parallel-oauth:${accountId}`,
    enabled: canEditControls,
    load: async (signal) => {
      const keys = await listKeyBalances("parallel", signal)
      return keys.some((key) => key.authMode === "oauth" && key.oauthConnected)
    },
  })

  const renderRateTier = (slotArgs: RateTierSlotArgs) => {
    if (slotArgs.providerId !== "tavily") return null
    const provider = providers.find((entry) => entry.id === "tavily")
    if (provider === undefined) return null
    return (
      <TavilyRateTierSelect
        provider={slotArgs.keyed ? { ...provider, keyVaultStatus: "configured" } : provider}
        canEdit={canEditControls}
        compact
        onConfirmed={slotArgs.onConfirmed}
        onUpdated={async () => {
          await refreshProviders()
          await refreshDashboard()
        }}
      />
    )
  }

  return (
    <QuotaPage
      manualQuotaEligible={manualQuotaEligible}
      refreshableProviders={oauth.status === "ready" && oauth.data ? new Set(["parallel"]) : new Set()}
      renderOAuthActions={({ providerId }) => (
        providerId === "parallel" && oauth.status === "ready" && !oauth.data
          ? <span className="text-[12px] text-[var(--muted)]">Connect Parallel in <a className="underline" href="/account/keys">Keys and pools</a></span>
          : null
      )}
      renderKeyBalances={canEditControls ? (providerId, providerName) => (
        <KeyBalances
          key={`${accountId}:${providerId}`}
          providerId={providerId}
          providerName={providerName}
          accountId={accountId}
          isAdmin
          email={null}
          refreshDashboard={refreshDashboard}
        />
      ) : undefined}
      renderRateTier={renderRateTier}
    />
  )
}
