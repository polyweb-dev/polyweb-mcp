import { useCallback, useEffect, useRef, useState, type RefObject } from "react"
import { useFreeSearch } from "@/context/useFreeSearch"
import { getStatusSummary } from "./statusSummary"
import {
  ProviderStatusPopover,
  PROVIDERS_POPOVER_ID,
} from "./ProviderStatusPopover"
import {
  FailoverStatusPopover,
  FAILOVER_POPOVER_ID,
} from "./FailoverStatusPopover"

type OpenPopover = "providers" | "failover" | null

interface DismissOptions {
  openPopover: OpenPopover
  anchorRef: RefObject<HTMLDivElement | null>
  providerTriggerRef: RefObject<HTMLButtonElement | null>
  failoverTriggerRef: RefObject<HTMLButtonElement | null>
  onClose: () => void
}

/** Outside-click + Escape dismissal with focus return to the opener. */
function useDismissPopover({
  openPopover,
  anchorRef,
  providerTriggerRef,
  failoverTriggerRef,
  onClose,
}: DismissOptions) {
  useEffect(() => {
    if (!openPopover) return

    const closeOnOutside = (event: MouseEvent) => {
      if (!anchorRef.current?.contains(event.target as Node)) {
        onClose()
      }
    }
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return
      const activeTrigger =
        openPopover === "providers"
          ? providerTriggerRef.current
          : failoverTriggerRef.current
      onClose()
      activeTrigger?.focus()
    }

    document.addEventListener("mousedown", closeOnOutside)
    document.addEventListener("keydown", closeOnEscape)
    return () => {
      document.removeEventListener("mousedown", closeOnOutside)
      document.removeEventListener("keydown", closeOnEscape)
    }
  }, [openPopover, anchorRef, providerTriggerRef, failoverTriggerRef, onClose])
}

export function StatusBar() {
  const {
    providers,
    fallbackConfig,
    routingPreset,
    routingLoading,
    routingError,
    canReadControls,
  } = useFreeSearch()
  const [openPopover, setOpenPopover] = useState<OpenPopover>(null)
  const anchorRef = useRef<HTMLDivElement>(null)
  const providerTriggerRef = useRef<HTMLButtonElement>(null)
  const failoverTriggerRef = useRef<HTMLButtonElement>(null)

  const closePopover = useCallback(() => setOpenPopover(null), [])

  const { eligibleProviders, providerCount, failoverStatus, showFailover } =
    getStatusSummary({
      providers,
      routingPreset,
      fallbackConfig,
      routingLoading,
      routingError,
    })

  useDismissPopover({
    openPopover,
    anchorRef,
    providerTriggerRef,
    failoverTriggerRef,
    onClose: closePopover,
  })

  return (
    <div
      ref={anchorRef}
      data-testid="status-bar"
      className="sticky bottom-0 relative flex h-6 shrink-0 items-center justify-end border-t border-[var(--border-subtle)] bg-[var(--elevated)] px-2 text-[12px] text-[var(--muted)] tnum gap-1"
    >
      {!canReadControls && <span className="px-2">Signed in</span>}

      {canReadControls && (
        <>
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
        <ProviderStatusPopover providers={providers} eligibleProviders={eligibleProviders} providerCount={providerCount} />
      )}

      {openPopover === "failover" && showFailover && (
        <FailoverStatusPopover fallbackConfig={fallbackConfig} failoverStatus={failoverStatus} />
      )}
        </>
      )}
    </div>
  )
}
