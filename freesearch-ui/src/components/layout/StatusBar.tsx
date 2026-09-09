import { useRef, useState } from "react"
import { useFreeSearch } from "@/context/useFreeSearch"
import { getEligibleProviders } from "@/components/routing/routingUtils"
import { FailoverPopover, FAILOVER_POPOVER_ID } from "./statusBar/FailoverPopover"
import {
  ProviderStatusPopover,
  PROVIDERS_POPOVER_ID,
} from "./statusBar/ProviderStatusPopover"
import { usePopoverDismiss, type OpenPopover } from "./statusBar/usePopoverDismiss"

export function StatusBar() {
  const {
    providers,
    fallbackConfig,
    routingPreset,
    routingLoading,
    routingError,
  } = useFreeSearch()
  const [openPopover, setOpenPopover] = useState<OpenPopover>(null)
  const anchorRef = useRef<HTMLDivElement>(null)
  const providerTriggerRef = useRef<HTMLButtonElement>(null)
  const failoverTriggerRef = useRef<HTMLButtonElement>(null)

  const eligibleProviders = getEligibleProviders(providers, "search", routingPreset)
  const providerCount = `${eligibleProviders.length} of ${providers.length} providers`
  const failoverStatus = `Failover ${fallbackConfig.enabled ? "active" : "inactive"}`
  const showFailover = !routingLoading && !routingError

  usePopoverDismiss(
    openPopover,
    anchorRef,
    providerTriggerRef,
    failoverTriggerRef,
    setOpenPopover,
  )

  return (
    <div
      ref={anchorRef}
      data-testid="status-bar"
      className="sticky bottom-0 relative flex h-6 shrink-0 items-center justify-end border-t border-[var(--border-subtle)] bg-[var(--elevated)] px-2 text-[12px] text-[var(--muted)] tnum gap-1"
    >
      <button
        ref={providerTriggerRef}
        type="button"
        aria-expanded={openPopover === "providers"}
        aria-controls={PROVIDERS_POPOVER_ID}
        onClick={() =>
          setOpenPopover((current) => (current === "providers" ? null : "providers"))
        }
        className="flex h-full items-center gap-1.5 rounded-sm px-2 text-left outline-none transition-colors hover:bg-white/5 hover:text-[var(--text-strong)] focus-visible:ring-1 focus-visible:ring-[var(--signal)]"
      >
        <span
          aria-hidden="true"
          className="size-1.5 rounded-full shrink-0"
          style={{
            background: eligibleProviders.length
              ? "var(--status-healthy)"
              : "var(--muted)",
          }}
        />
        <span>{providerCount}</span>
      </button>

      {showFailover && (
        <button
          ref={failoverTriggerRef}
          type="button"
          aria-expanded={openPopover === "failover"}
          aria-controls={FAILOVER_POPOVER_ID}
          onClick={() =>
            setOpenPopover((current) => (current === "failover" ? null : "failover"))
          }
          className="flex h-full items-center gap-1.5 rounded-sm px-2 text-left outline-none transition-colors hover:bg-white/5 hover:text-[var(--text-strong)] focus-visible:ring-1 focus-visible:ring-[var(--signal)]"
        >
          <span
            aria-hidden="true"
            className="size-1.5 rounded-full shrink-0"
            style={{
              background: fallbackConfig.enabled
                ? "var(--status-healthy)"
                : "var(--muted)",
            }}
          />
          <span>{failoverStatus}</span>
        </button>
      )}

      {routingLoading && <span className="px-2">Loading routing status</span>}
      {routingError && <span className="px-2 text-[var(--status-danger)]">Routing status unavailable</span>}

      {openPopover === "providers" && (
        <ProviderStatusPopover
          providers={providers}
          eligibleProviders={eligibleProviders}
          providerCount={providerCount}
        />
      )}

      {openPopover === "failover" && showFailover && (
        <FailoverPopover
          fallbackConfig={fallbackConfig}
          failoverStatus={failoverStatus}
        />
      )}
    </div>
  )
}
