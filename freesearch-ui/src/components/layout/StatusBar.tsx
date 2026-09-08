import { useEffect, useRef, useState } from "react"
import { useFreeSearch } from "@/context/useFreeSearch"
import { getEligibleProviders } from "@/components/routing/routingUtils"

const PROVIDERS_POPOVER_ID = "provider-status-details"
const FAILOVER_POPOVER_ID = "failover-status-details"

export function StatusBar() {
  const {
    providers,
    fallbackConfig,
    routingPreset,
    routingLoading,
    routingError,
  } = useFreeSearch()
  const [openPopover, setOpenPopover] = useState<"providers" | "failover" | null>(null)
  const anchorRef = useRef<HTMLDivElement>(null)
  const providerTriggerRef = useRef<HTMLButtonElement>(null)
  const failoverTriggerRef = useRef<HTMLButtonElement>(null)

  const eligibleProviders = getEligibleProviders(providers, "search", routingPreset)
  const providerCount = `${eligibleProviders.length} of ${providers.length} providers`
  const failoverStatus = `Failover ${fallbackConfig.enabled ? "active" : "inactive"}`
  const showFailover = !routingLoading && !routingError

  useEffect(() => {
    if (!openPopover) return

    const closeOnOutside = (event: MouseEvent) => {
      if (!anchorRef.current?.contains(event.target as Node)) {
        setOpenPopover(null)
      }
    }
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return
      const activeTrigger =
        openPopover === "providers"
          ? providerTriggerRef.current
          : failoverTriggerRef.current
      setOpenPopover(null)
      activeTrigger?.focus()
    }

    document.addEventListener("mousedown", closeOnOutside)
    document.addEventListener("keydown", closeOnEscape)
    return () => {
      document.removeEventListener("mousedown", closeOnOutside)
      document.removeEventListener("keydown", closeOnEscape)
    }
  }, [openPopover])

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
        <section
          id={PROVIDERS_POPOVER_ID}
          role="dialog"
          aria-label="Provider routing details"
          className="absolute bottom-full right-24 mb-1.5 w-72 rounded-md border border-[var(--border-subtle)] bg-[var(--elevated)] p-3 text-[12px] text-[var(--text)] shadow-xl"
        >
          <div className="flex items-center justify-between border-b border-[var(--border-subtle)] pb-2">
            <strong className="font-medium text-[var(--text-strong)]">Provider routing</strong>
            <span>{providerCount}</span>
          </div>
          <div className="space-y-1.5 py-2">
            {providers.map((provider) => (
              <div key={provider.id} className="flex items-center justify-between gap-3">
                <span className="truncate">{provider.name}</span>
                <span
                  className={
                    eligibleProviders.some(({ id }) => id === provider.id)
                      ? "text-[var(--status-healthy)]"
                      : "text-[var(--muted)]"
                  }
                >
                  {eligibleProviders.some(({ id }) => id === provider.id)
                    ? "Eligible"
                    : "Unavailable"}
                </span>
              </div>
            ))}
          </div>
        </section>
      )}

      {openPopover === "failover" && showFailover && (
        <section
          id={FAILOVER_POPOVER_ID}
          role="dialog"
          aria-label="Failover settings details"
          className="absolute bottom-full right-2 mb-1.5 w-72 rounded-md border border-[var(--border-subtle)] bg-[var(--elevated)] p-3 text-[12px] text-[var(--text)] shadow-xl"
        >
          <div className="flex items-center justify-between border-b border-[var(--border-subtle)] pb-2">
            <strong className="font-medium text-[var(--text-strong)]">Failover settings</strong>
            <span
              className={
                fallbackConfig.enabled
                  ? "font-medium text-[var(--status-healthy)]"
                  : "text-[var(--muted)]"
              }
            >
              {failoverStatus}
            </span>
          </div>
          <div className="space-y-2 py-2">
            <div className="flex items-center justify-between gap-2">
              <span className="text-[var(--muted)]">Fallback chaining</span>
              <span className="text-[var(--text-strong)]">
                {fallbackConfig.enabled ? "Chained (active)" : "Single-shot"}
              </span>
            </div>
            <div className="flex items-center justify-between gap-2">
              <span className="text-[var(--muted)]">Cascade depth</span>
              <span className="text-[var(--text-strong)] tnum">
                {fallbackConfig.enabled
                  ? `Up to ${fallbackConfig.maxAttempts} hops`
                  : "1 hop"}
              </span>
            </div>
            <div className="border-t border-[var(--border-subtle)] pt-2 pb-1 text-[11px] font-medium uppercase tracking-wider text-[var(--muted)]">
              Conditions
            </div>
            <div className="flex items-center justify-between gap-2">
              <span>Rate limit (429)</span>
              <span
                className={
                  fallbackConfig.fallbackOnRateLimit
                    ? "text-[var(--status-healthy)]"
                    : "text-[var(--muted)]"
                }
              >
                {fallbackConfig.fallbackOnRateLimit ? "Enabled" : "Disabled"}
              </span>
            </div>
            <div className="flex items-center justify-between gap-2">
              <span>Timeout</span>
              <span
                className={
                  fallbackConfig.fallbackOnTimeout
                    ? "text-[var(--status-healthy)]"
                    : "text-[var(--muted)]"
                }
              >
                {fallbackConfig.fallbackOnTimeout ? "Enabled" : "Disabled"}
              </span>
            </div>
            <div className="flex items-center justify-between gap-2">
              <span>Server error (5xx)</span>
              <span
                className={
                  fallbackConfig.fallbackOnServerError
                    ? "text-[var(--status-healthy)]"
                    : "text-[var(--muted)]"
                }
              >
                {fallbackConfig.fallbackOnServerError ? "Enabled" : "Disabled"}
              </span>
            </div>
          </div>
        </section>
      )}
    </div>
  )
}
