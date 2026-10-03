import type { CSSProperties, ReactNode } from "react"
import { cn } from "cn"

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

/**
 * One grid template for the ruler and every row, so every track shares an
 * origin: below `sm` the label sits above a full-width track with its value on
 * the label line, and from `sm` up they are three aligned columns.
 */
const ROW_GRID_CLASS =
  "grid min-w-0 grid-cols-[minmax(0,1fr)_auto] items-center gap-x-3 gap-y-1 sm:grid-cols-[minmax(0,10rem)_minmax(0,1fr)_auto]"
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
    "tnum absolute bottom-1 text-[10px] leading-none text-[var(--muted)]",
    percent > 0 && percent < PERCENT_SCALE && "-translate-x-1/2",
    percent >= PERCENT_SCALE && "-translate-x-full"
  )
}

function renderRuler(totalMs: number, hasScale: boolean) {
  return (
    <div aria-hidden="true" className="relative h-5 min-w-0">
      <div className="absolute inset-x-0 bottom-0 h-px bg-[var(--border-subtle)]" />
      {hasScale &&
        TICK_PERCENTS.map((percent) => (
          <span key={percent} className={tickLabelClass(percent)} style={{ left: `${percent}%` }}>
            {Math.round((totalMs * percent) / PERCENT_SCALE)}
          </span>
        ))}
    </div>
  )
}

/** The ruler occupies the same grid cell as a track, so both columns share one x origin. */
function renderRulerRow(totalMs: number, hasScale: boolean) {
  return (
    <div className={ROW_GRID_CLASS}>
      <span aria-hidden="true" className="hidden sm:block" />
      <div className={TRACK_CELL_CLASS}>{renderRuler(totalMs, hasScale)}</div>
    </div>
  )
}

function renderRow(row: LatencyWaterfallRow, totalMs: number) {
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
      <li key={row.id} className={ROW_GRID_CLASS}>
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
          ROW_GRID_CLASS,
          "w-full rounded-sm px-1 py-0.5 text-left transition-colors motion-reduce:transition-none",
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

export function LatencyWaterfall({ rows, totalMs, ariaLabel }: LatencyWaterfallProps) {
  const hasScale = Number.isFinite(totalMs) && totalMs > 0

  return (
    <div className="min-w-0">
      {/* the ruler is decorative; this states the scale for screen readers */}
      <p className="sr-only">Timeline scale 0 to {totalMs} milliseconds</p>
      {renderRulerRow(totalMs, hasScale)}
      <ol role="list" aria-label={ariaLabel} className="m-0 list-none space-y-1 p-0">
        {rows.length === 0 ? (
          <li className="text-[12px] text-[var(--muted)]">No timing was recorded.</li>
        ) : (
          rows.map((row) => renderRow(row, totalMs))
        )}
      </ol>
    </div>
  )
}
