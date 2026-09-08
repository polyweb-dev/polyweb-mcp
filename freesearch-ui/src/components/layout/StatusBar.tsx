import { useEffect, useRef, useState } from "react"
import { useFreeSearch } from "@/context/useFreeSearch"
import { getEligibleProviders } from "@/components/routing/routingUtils"

const POPOVER_ID = "provider-status-details"

export function StatusBar() {
  const {
    providers,
    fallbackConfig,
    routingPreset,
    routingLoading,
    routingError,
  } = useFreeSearch()
  const [open, setOpen] = useState(false)
  const anchorRef = useRef<HTMLDivElement>(null)
  const triggerRef = useRef<HTMLButtonElement>(null)
  const eligibleProviders = getEligibleProviders(providers, "search", routingPreset)
  const providerCount = `${eligibleProviders.length} of ${providers.length} providers`
  const failoverStatus = `Failover ${fallbackConfig.enabled ? "active" : "inactive"}`
  const showFailover = !routingLoading && !routingError

  useEffect(() => {
    if (!open) return

    const closeOnOutside = (event: MouseEvent) => {
      if (!anchorRef.current?.contains(event.target as Node)) setOpen(false)
    }
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return
      setOpen(false)
      triggerRef.current?.focus()
    }

    document.addEventListener("mousedown", closeOnOutside)
    document.addEventListener("keydown", closeOnEscape)
    return () => {
      document.removeEventListener("mousedown", closeOnOutside)
      document.removeEventListener("keydown", closeOnEscape)
    }
  }, [open])

  return (
    <div
      ref={anchorRef}
      data-testid="status-bar"
      className="sticky bottom-0 relative flex h-6 shrink-0 items-center justify-between border-t border-[var(--border-subtle)] bg-[var(--elevated)] px-3 text-[12px] text-[var(--muted)] tnum"
    >
      <button
        ref={triggerRef}
        type="button"
        aria-expanded={open}
        aria-controls={POPOVER_ID}
        onClick={() => setOpen((current) => !current)}
        className="flex h-full items-center gap-2 rounded-sm px-1 text-left outline-none hover:text-[var(--text-strong)] focus-visible:ring-1 focus-visible:ring-[var(--signal)]"
      >
        <span
          aria-hidden="true"
          className="size-1.5 rounded-full"
          style={{
            background: eligibleProviders.length
              ? "var(--status-healthy)"
              : "var(--muted)",
          }}
        />
        <span>{providerCount}</span>
        {showFailover && <span>{failoverStatus}</span>}
        {routingLoading && <span>Loading routing status</span>}
        {routingError && <span>Routing status unavailable</span>}
      </button>

      <span>{routingPreset}</span>

      {open && (
        <section
          id={POPOVER_ID}
          role="dialog"
          aria-label="Provider and failover details"
          className="absolute bottom-full left-2 mb-2 w-72 rounded-md border border-[var(--border-subtle)] bg-[var(--elevated)] p-3 text-[12px] text-[var(--text)] shadow-xl"
        >
          <div className="flex items-center justify-between border-b border-[var(--border-subtle)] pb-2">
            <strong className="font-medium text-[var(--text-strong)]">Provider routing</strong>
            <span>{providerCount}</span>
          </div>
          <div className="space-y-1.5 py-2">
            {providers.map((provider) => (
              <div key={provider.id} className="flex items-center justify-between gap-3">
                <span className="truncate">{provider.name}</span>
                <span>{eligibleProviders.some(({ id }) => id === provider.id) ? "Eligible" : "Unavailable"}</span>
              </div>
            ))}
          </div>
          {showFailover && (
            <div className="border-t border-[var(--border-subtle)] pt-2">{failoverStatus}</div>
          )}
        </section>
      )}
    </div>
  )
}
