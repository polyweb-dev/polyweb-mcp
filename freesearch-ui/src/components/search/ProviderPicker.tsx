import type { ProviderConfig } from "@/types/freesearch"

type ProviderPickerOptions = {
  eligibleProviders: ProviderConfig[]
  selectedProviderId: string
  onProviderChange: (providerId: string) => void
}

export function ProviderPicker({
  eligibleProviders,
  selectedProviderId,
  onProviderChange,
}: ProviderPickerOptions) {
  return (
    <div className="flex items-center gap-2">
      <span>Provider:</span>
      <select
        value={selectedProviderId}
        onChange={(e) => onProviderChange(e.target.value)}
        className="rounded border border-[var(--border-subtle)] bg-[var(--elevated)] px-2.5 py-1 text-[13px] text-[var(--text)] outline-none"
      >
        <option value="auto">Auto arbitration</option>
        {eligibleProviders.map((provider) => (
          <option key={provider.id} value={provider.id}>
            {provider.name}
          </option>
        ))}
      </select>
    </div>
  )
}
