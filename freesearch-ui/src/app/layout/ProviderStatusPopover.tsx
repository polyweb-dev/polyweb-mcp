import type { ProviderConfig } from "@/domains/providers"

export const PROVIDERS_POPOVER_ID = "provider-status-details"

interface ProviderStatusPopoverProps {
  providers: ProviderConfig[]
  eligibleProviders: ProviderConfig[]
  providerCount: string
}

export function ProviderStatusPopover({
  providers,
  eligibleProviders,
  providerCount,
}: ProviderStatusPopoverProps) {
  return (
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
  )
}
