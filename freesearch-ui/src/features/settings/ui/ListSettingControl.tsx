import { X } from "lucide-react"
import { toBackendId } from "@/domains/providers"
import { Button } from "@/shared/ui/button"
import { ProviderBadge } from "@/shared/ui/ProviderBadge"
import { ProviderLogo } from "@/shared/ui/ProviderLogo"
import { Select } from "@/shared/ui/select"
import { PREFERRED_PROVIDER_OPTIONS, providerLabel, providerLogoId } from "../model/settingsFormat"

interface ListSettingControlProps {
  id: string
  label: string
  value: readonly string[]
  disabled: boolean
  onChange: (value: string[]) => void
}

/**
 * Ordered provider picker of the preferred providers field: one chip per
 * chosen provider in preference order, each with its logo and a remove
 * button, then an "Add provider" select of the providers not chosen yet. The
 * value stays the list of wire provider ids.
 */
export function ListSettingControl({ id, label, value, disabled, onChange }: ListSettingControlProps) {
  const remaining = PREFERRED_PROVIDER_OPTIONS.filter((option) => !value.includes(option.value)).map((option) => ({
    value: option.logoId,
    label: option.label,
    icon: <ProviderLogo providerId={option.logoId} />,
  }))
  return (
    <div className="space-y-2">
      {value.length > 0 && (
        <ol aria-label={label} className="flex flex-wrap gap-1.5">
          {value.map((provider, index) => (
            <li
              key={provider}
              className="inline-flex h-7 items-center gap-1.5 rounded-md border border-[var(--border-subtle)] bg-[var(--surface)] pr-0.5 pl-2 text-[13px] text-[var(--text-strong)]"
            >
              <span className="tnum text-[11px] text-[var(--muted)]">{index + 1}</span>
              <ProviderBadge providerId={providerLogoId(provider)} name={providerLabel(provider)} />
              <Button
                variant="ghost"
                size="icon-xs"
                aria-label={`Remove ${providerLabel(provider)}`}
                disabled={disabled}
                onClick={() => onChange(value.filter((item) => item !== provider))}
              >
                <X aria-hidden="true" />
              </Button>
            </li>
          ))}
        </ol>
      )}
      {remaining.length > 0 && (
        <Select
          id={id}
          ariaLabel="Add preferred provider"
          value=""
          placeholder="Add provider"
          options={remaining}
          disabled={disabled}
          onValueChange={(next) => onChange([...value, toBackendId(next)])}
        />
      )}
    </div>
  )
}
