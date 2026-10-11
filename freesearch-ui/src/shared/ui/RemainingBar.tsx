import type { ReactNode } from "react"

/** One shared remaining-capacity bar for funds use and rate use. */
export interface RemainingBarProps {
  /** The remaining percentage, or null when the caller knows no percentage. */
  percentRemaining: number | null
  /** The accessible name, supplied by the caller. */
  label: string
  /** The optional accessible value text, supplied by the caller. */
  valueText?: string
}

/** The current rounded track of the funds and rate bars. */
const TRACK = "h-1.5 w-full overflow-hidden rounded-full bg-[var(--border-subtle)]"

/**
 * The color band of one remaining percentage.
 *
 * Green stays above 75, yellow covers 50 through 75, orange covers 25 without
 * 50, and red stays below 25. The band boundaries remove the mid-point overlap
 * of the requirements text: exactly 75 and exactly 50 show yellow, exactly 25
 * shows orange. The theme holds no orange status token, so orange reuses the
 * Tailwind `bg-orange-500` class.
 *
 * The helper ships beside the component on purpose: the plan pins this file for
 * both the component and its observable color result.
 */
// eslint-disable-next-line react-refresh/only-export-components
export function remainingColor(percent: number): string {
  if (percent > 75) return "bg-[var(--status-healthy)]"
  if (percent >= 50) return "bg-[var(--status-warning)]"
  if (percent >= 25) return "bg-orange-500"
  return "bg-[var(--status-danger)]"
}

/**
 * One full-width bar with its own line: percent-driven width, color, and value.
 *
 * A null or non-finite percentage yields no bar, so an unknown capacity never
 * renders as empty capacity. A finite percentage is clamped to zero through
 * 100, and the clamped value drives the width, the color, and `aria-valuenow`.
 * This component holds no text and no provider logic; the caller owns the
 * label, the value text, and everything around the bar.
 */
export function RemainingBar({
  percentRemaining,
  label,
  valueText,
}: RemainingBarProps): ReactNode {
  if (percentRemaining === null || !Number.isFinite(percentRemaining)) return null
  const percent = Math.min(100, Math.max(0, percentRemaining))
  return (
    <div
      className={TRACK}
      role="progressbar"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={percent}
      {...(valueText === undefined ? {} : { "aria-valuetext": valueText })}
    >
      <div
        className={"h-full rounded-full " + remainingColor(percent)}
        style={{ width: percent + "%" }}
      />
    </div>
  )
}
