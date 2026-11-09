import type { CSSProperties, ReactNode } from "react"
import { cn } from "cn"

export { LatencyWaterfallValue } from "./LatencyWaterfallValue"
export type { LatencyWaterfallValueProps } from "./LatencyWaterfallValue"

export interface LatencyWaterfallSegment {
  offsetMs: number
  durationMs: number
  color: string
}

export interface LatencyWaterfallRow {
  id: string
  label: ReactNode
  segments: readonly LatencyWaterfallSegment[]
  value: ReactNode
  /** Nesting level of the row inside its hierarchy; 0 or undefined is a root. */
  depth?: number
  /** Marks the row as the current selection (only meaningful with `onSelect`). */
  selected?: boolean
  /** When present the row becomes a keyboard-operable selection button. */
  onSelect?: () => void
}

export interface LatencyWaterfallProps {
  rows: readonly LatencyWaterfallRow[]
  totalMs: number
  ariaLabel: string
  /** Keeps the time axis visible while the rows scroll under it. */
  stickyRuler?: boolean
  /** Shows only start, midpoint, and end ticks in a narrow timeline pane. */
  compactRuler?: boolean
  /** Gives the shared ruler/row track more room by reserving less value-column width. */
  expandedTrack?: boolean
}

/** A segment whose geometry is already clamped inside the track. */
interface PlacedSegment {
  leftPct: number
  widthPct: number
  color: string
}

/** Sub-half-percent durations would round away entirely; keep a visible sliver instead. */
const MIN_VISIBLE_WIDTH_PCT = 0.5
const PERCENT_SCALE = 100
const PERCENT_PRECISION = 10000
const TICK_PERCENTS = [0, 25, 50, 75, 100] as const
const COMPACT_TICK_PERCENTS = [0, 50, 100] as const

/**
 * One grid template for the ruler and every row, so every track shares an
 * origin and an endpoint: below `sm` the label sits above a full-width track
 * with its value on the label line, and from `sm` up they are three aligned
 * columns with a fixed-width value column.
 */
const ROW_GRID_CLASS =
  "grid min-w-0 grid-cols-[minmax(0,1fr)_auto] items-center gap-x-3 gap-y-1 sm:grid-cols-[minmax(0,10rem)_minmax(0,1fr)_7rem]"
const EXPANDED_TRACK_ROW_GRID_CLASS =
  "grid min-w-0 grid-cols-[minmax(0,1fr)_auto] items-center gap-x-3 gap-y-1 sm:grid-cols-[minmax(0,10rem)_minmax(0,1fr)_5rem]"
/** Every row and the ruler carry the same inset, so their tracks stay aligned. */
const ROW_INSET_CLASS = "px-1 py-0.5"
const ROW_HEIGHT_CLASS = "min-h-[32px]"
const TRACK_CELL_CLASS =
  "col-span-2 col-start-1 row-start-2 sm:col-span-1 sm:col-start-2 sm:row-start-1"
const LABEL_CELL_CLASS = "min-w-0 break-words text-[12px] text-[var(--text)]"
const VALUE_CELL_CLASS =
  "tnum col-start-2 row-start-1 min-w-0 text-right text-[12px] text-[var(--text-strong)] sm:col-start-3"

function roundPercent(value: number): number {
  return Math.round(value * PERCENT_PRECISION) / PERCENT_PRECISION
}

/** Clamps the offset into the track and the width into whatever room is left. */
function placeSegment(segment: LatencyWaterfallSegment, totalMs: number): PlacedSegment | null {
  const { offsetMs, durationMs } = segment
  if (!Number.isFinite(offsetMs) || !Number.isFinite(durationMs) || durationMs < 0) return null
  const leftMs = Math.min(Math.max(offsetMs, 0), totalMs)
  const leftPct = roundPercent((leftMs / totalMs) * PERCENT_SCALE)
  const roomPct = PERCENT_SCALE - leftPct
  if (roomPct <= 0) return null
  const visibleMs = Math.min(durationMs, totalMs - leftMs)
  const widthPct = Math.min(
    Math.max(roundPercent((visibleMs / totalMs) * PERCENT_SCALE), MIN_VISIBLE_WIDTH_PCT),
    roomPct
  )
  return { leftPct, widthPct: roundPercent(widthPct), color: segment.color }
}

/** totalMs <= 0 carries no scale at all: an empty track beats NaN or Infinity widths. */
function placedSegments(row: LatencyWaterfallRow, totalMs: number): readonly PlacedSegment[] {
  if (!(totalMs > 0)) return []
  const placed: PlacedSegment[] = []
  for (const segment of row.segments) {
    const geometry = placeSegment(segment, totalMs)
    if (geometry !== null) placed.push(geometry)
  }
  return placed
}

function renderSegments(segments: readonly PlacedSegment[]) {
  return segments.map((segment, index) => (
    <span
      key={`${index}:${segment.leftPct}`}
      className="absolute inset-y-0 transition-[width] duration-300 motion-reduce:transition-none"
      style={{
        left: `${segment.leftPct}%`,
        width: `${segment.widthPct}%`,
        background: segment.color,
      }}
    />
  ))
}

function renderTrack(segments: readonly PlacedSegment[]) {
  return (
    <div
      aria-hidden="true"
      className="relative h-2 w-full overflow-hidden rounded-sm"
      style={{ background: "var(--surface)", boxShadow: "inset 0 0 0 1px var(--border-subtle)" }}
    >
      {renderSegments(segments)}
    </div>
  )
}

/**
 * Hierarchy indentation stays inside the label cell, so every track keeps the
 * one shared x origin the ruler establishes at any depth.
 */
function labelIndent(depth: number | undefined): CSSProperties | undefined {
  if (depth === undefined || depth <= 0) return undefined
  return {
    paddingLeft: depth * 12,
    marginLeft: 2,
    borderLeft: "1px solid var(--border-subtle)",
  }
}

function tickLabelClass(percent: number): string {
  return cn(
    "tnum absolute bottom-1 whitespace-nowrap text-[10px] leading-none text-[var(--muted)]",
    percent > 0 && percent < PERCENT_SCALE && "-translate-x-1/2",
    percent >= PERCENT_SCALE && "-translate-x-full"
  )
}

/** The smallest 1, 2, 2.5 or 5 × 10ⁿ step that splits `totalMs` into at most `intervals` parts. */
function roundStep(totalMs: number, intervals: number): number {
  const raw = totalMs / intervals
  const magnitude = 10 ** Math.floor(Math.log10(raw))
  const factor = [1, 2, 2.5, 5, 10].find((candidate) => candidate * magnitude >= raw) ?? 10
  return factor * magnitude
}

/**
 * Ticks at round values (0 / 200 / 400 / 600 for a 719 ms trace) placed
 * against the exact extent, so the plot still ends at the real request end.
 * A last tick crowding the end label gives way.
 */
function tickValues(totalMs: number, compact: boolean): number[] {
  const intervals = (compact ? COMPACT_TICK_PERCENTS : TICK_PERCENTS).length - 1
  if (totalMs <= 0) return [0]
  const step = roundStep(totalMs, intervals)
  const values: number[] = []
  for (let value = 0; value <= totalMs + 1e-9; value += step) values.push(Math.round(value * 100) / 100)
  return values
}

/** Ticks stay bare numbers; the millisecond unit lives outside the axis track. */
function tickText(value: number): string {
  return Math.round(value).toLocaleString("en-US")
}

function renderRuler(totalMs: number, hasScale: boolean, compact: boolean) {
  const ticks = tickValues(totalMs, compact).map((value) => ({
    value,
    percent: totalMs > 0 ? (value / totalMs) * PERCENT_SCALE : 0,
  }))
  return (
    <div aria-hidden="true" className="relative h-5 min-w-0">
      <div className="absolute inset-x-0 bottom-0 h-px bg-[var(--border-subtle)]" />
      {hasScale &&
        ticks.map(({ value, percent }) => (
          <span
            key={`${value}-guide`}
            className="absolute bottom-0 top-0 w-px bg-[var(--border-subtle)]"
            style={{ left: `${percent}%` }}
          />
        ))}
      {hasScale &&
        ticks.map(({ value, percent }) => (
          <span key={value} className={tickLabelClass(percent)} style={{ left: `${percent}%` }}>
            {tickText(value)}
          </span>
        ))}
    </div>
  )
}

/** The ruler occupies the same grid cell as a track, so both columns share one x origin. */
function renderRulerRow(
  totalMs: number,
  hasScale: boolean,
  sticky: boolean,
  { compact, rowGridClass }: { compact: boolean; rowGridClass: string }
) {
  return (
    <div
      className={cn(rowGridClass, sticky && "sticky top-0 z-10")}
      style={sticky ? { background: "var(--elevated)" } : undefined}
    >
      <span aria-hidden="true" className="hidden sm:block" />
      <div className={TRACK_CELL_CLASS}>{renderRuler(totalMs, hasScale, compact)}</div>
      {hasScale ? (
        <span aria-hidden="true" className={cn(VALUE_CELL_CLASS, "text-[11px] text-[var(--muted)]")}>
          ms
        </span>
      ) : null}
    </div>
  )
}

function renderRow(row: LatencyWaterfallRow, totalMs: number, rowGridClass: string) {
  const cells = (
    <>
      <span className={LABEL_CELL_CLASS} style={labelIndent(row.depth)}>
        {row.label}
      </span>
      <div className={TRACK_CELL_CLASS}>{renderTrack(placedSegments(row, totalMs))}</div>
      <span className={VALUE_CELL_CLASS}>{row.value}</span>
    </>
  )
  if (row.onSelect === undefined) {
    return (
      <li key={row.id} className={cn(rowGridClass, ROW_HEIGHT_CLASS)}>
        {cells}
      </li>
    )
  }
  return (
    <li key={row.id} className="min-w-0">
      <button
        type="button"
        aria-pressed={row.selected === true}
        data-depth={row.depth ?? 0}
        onClick={row.onSelect}
        className={cn(
          rowGridClass,
          ROW_HEIGHT_CLASS,
          // The ring is inset because the scroll container hides horizontal
          // overflow: an outer ring would lose its left edge there.
          "w-full rounded-sm text-left transition-colors motion-reduce:transition-none",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-[var(--signal)]/40",
          row.selected === true
            ? "bg-[var(--signal-muted)] shadow-[inset_2px_0_0_0_var(--signal)]"
            : "hover:bg-[var(--surface)]"
        )}
      >
        {cells}
      </button>
    </li>
  )
}

export function LatencyWaterfall({
  rows,
  totalMs,
  ariaLabel,
  stickyRuler = false,
  compactRuler = false,
  expandedTrack = false,
}: LatencyWaterfallProps) {
  const hasScale = Number.isFinite(totalMs) && totalMs > 0
  const rowGridClass = cn(
    expandedTrack ? EXPANDED_TRACK_ROW_GRID_CLASS : ROW_GRID_CLASS,
    expandedTrack ? "py-0.5" : ROW_INSET_CLASS
  )

  return (
    <div className="min-w-0">
      {/* the ruler is decorative; this states the scale for screen readers */}
      <p className="sr-only">Timeline scale 0 to {totalMs} milliseconds</p>
      {renderRulerRow(totalMs, hasScale, stickyRuler, { compact: compactRuler, rowGridClass })}
      <ol role="list" aria-label={ariaLabel} className="m-0 list-none space-y-1 p-0">
        {rows.length === 0 ? (
          <li className="text-[12px] text-[var(--muted)]">No timing was recorded.</li>
        ) : (
          rows.map((row) => renderRow(row, totalMs, rowGridClass))
        )}
      </ol>
    </div>
  )
}
