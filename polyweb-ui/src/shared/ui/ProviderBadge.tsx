import type { ReactNode } from "react"
import { cn } from "cn"
import { ProviderLogo } from "./ProviderLogo"

export interface ProviderBadgeProps {
  providerId: string
  name: string
  className?: string
  logoClassName?: string
  /**
   * Text that belongs to the same line as the name (for example ` request`).
   * It renders inside the name element, so the logo, the name, and the suffix
   * are one vertically centered flex row rather than a badge followed by loose
   * inline text on a different baseline.
   */
  suffix?: string
  /** The mark of an identity with no catalog logo; the letter avatar is the default. */
  fallback?: ReactNode
}

/**
 * One provider identity everywhere: the catalog logo followed by the provider
 * name. Presentation only — the caller resolves the id and the name at its own
 * feature or domain boundary.
 */
export function ProviderBadge({
  providerId,
  name,
  className,
  logoClassName,
  suffix,
  fallback,
}: ProviderBadgeProps): ReactNode {
  return (
    <span className={cn("inline-flex min-w-0 items-center gap-1.5", className)}>
      <ProviderLogo
        providerId={providerId}
        name={name}
        className={logoClassName}
        fallback={fallback}
      />
      <span className="min-w-0 [overflow-wrap:anywhere]">
        {name}
        {suffix}
      </span>
    </span>
  )
}
