import type { ReactNode } from "react"
import { cn } from "cn"
import { ProviderLogo } from "./ProviderLogo"

export interface ProviderBadgeProps {
  providerId: string
  name: string
  className?: string
  logoClassName?: string
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
      <span className="min-w-0 [overflow-wrap:anywhere]">{name}</span>
    </span>
  )
}
