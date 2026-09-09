import React from "react"
import braveLogo from "@/assets/brave.webp"
import exaLogo from "@/assets/exa.webp"
import firecrawlLogo from "@/assets/firecrawl.webp"
import keenableLogo from "@/assets/keenable.webp"
import parallelLogo from "@/assets/parallel.webp"
import tavilyLogo from "@/assets/tavily.webp"
import youcomLogo from "@/assets/youcom.webp"
import { cn } from "@/lib/utils"

const LOGO_MAP: Record<string, string> = {
  brave: braveLogo,
  "brave search": braveLogo,
  exa: exaLogo,
  firecrawl: firecrawlLogo,
  keenable: keenableLogo,
  parallel: parallelLogo,
  tavily: tavilyLogo,
  youcom: youcomLogo,
  "you.com": youcomLogo,
}

export interface ProviderLogoProps {
  providerId?: string
  name?: string
  className?: string
}

export const ProviderLogo: React.FC<ProviderLogoProps> = ({
  providerId,
  name,
  className,
}) => {
  if (!providerId && !name) return null
  const key = (providerId || name || "").toLowerCase().trim()
  const logo = LOGO_MAP[key]

  if (!logo) {
    const fallbackLetter = (name || providerId || "?").trim().charAt(0).toUpperCase()
    return (
      <span
        aria-hidden="true"
        data-testid="provider-logo-fallback"
        className={cn(
          "inline-flex size-4 items-center justify-center rounded bg-[var(--elevated)] text-[9px] font-bold text-[var(--muted)] border border-[var(--border-subtle)] shrink-0 select-none",
          className
        )}
      >
        {fallbackLetter}
      </span>
    )
  }

  return (
    <img
      src={logo}
      alt=""
      aria-hidden="true"
      data-testid={`provider-logo-${key}`}
      className={cn("size-4 rounded-sm object-contain shrink-0", className)}
    />
  )
}
