import { useState } from "react"
import { cn } from "cn"

export interface JsonViewerProps {
  value: unknown
  ariaLabel: string
  defaultExpandedDepth?: number
  className?: string
}

/** Scalar classes map onto the three restrained accents, plus muted for absence. */
type TokenKind = "string" | "number" | "boolean" | "null"

interface JsonToken {
  text: string
  kind: TokenKind
}

interface JsonEntry {
  key?: string
  value: unknown
}

interface NodeContext {
  path: string
  depth: number
  isLast: boolean
  key?: string
  open: Readonly<Record<string, boolean | undefined>>
  setNodeOpen: (path: string, next: boolean) => void
  defaultExpandedDepth: number
}

const TOKEN_COLOR: Record<TokenKind, string> = {
  string: "var(--accent-seafoam)",
  number: "var(--accent-gold)",
  boolean: "var(--accent-gold)",
  null: "var(--muted)",
}

const LINE_CLASS = "min-w-0"
const PUNCTUATION_CLASS = "text-[var(--text)]"
const SUMMARY_CLASS =
  "min-w-0 cursor-pointer list-item select-none marker:text-[var(--muted)]"
const CHILD_BLOCK_CLASS = "min-w-0 border-l border-[var(--border-subtle)] pl-3"
const WRAPPER_CLASS =
  "mono min-w-0 max-h-72 overflow-y-auto overflow-x-hidden whitespace-pre-wrap [overflow-wrap:anywhere] text-[12px] leading-relaxed"

/** Values JSON cannot represent still render as text rather than throwing. */
function fallbackText(value: unknown): string {
  if (typeof value === "undefined") return "undefined"
  try {
    return String(value)
  } catch {
    return "null"
  }
}

function scalarToken(value: unknown): JsonToken {
  if (typeof value === "string") return { text: JSON.stringify(value), kind: "string" }
  if (typeof value === "number") {
    return Number.isFinite(value)
      ? { text: String(value), kind: "number" }
      : { text: "null", kind: "null" }
  }
  if (typeof value === "boolean") return { text: String(value), kind: "boolean" }
  if (value === null) return { text: "null", kind: "null" }
  return { text: fallbackText(value), kind: "null" }
}

function isContainer(value: unknown): value is object {
  return typeof value === "object" && value !== null
}

function containerEntries(value: object): readonly JsonEntry[] {
  if (Array.isArray(value)) return (value as readonly unknown[]).map((item) => ({ value: item }))
  return Object.keys(value).map((key) => ({
    key,
    value: (value as Record<string, unknown>)[key],
  }))
}

function countHint(count: number, isArray: boolean): string {
  const noun = isArray ? "item" : "key"
  return `${count} ${count === 1 ? noun : `${noun}s`}`
}

/** JSON discipline: only the last child of a parent drops the separator. */
function renderTrailingComma(isLast: boolean) {
  return isLast ? null : ","
}

function renderKeyPrefix(key: string | undefined) {
  if (key === undefined) return null
  return (
    <>
      <span style={{ color: "var(--accent-cyan)" }}>{JSON.stringify(key)}</span>
      <span className={PUNCTUATION_CLASS}>{": "}</span>
    </>
  )
}

function renderScalarLine(value: unknown, context: NodeContext) {
  const token = scalarToken(value)
  return (
    <div className={LINE_CLASS}>
      {renderKeyPrefix(context.key)}
      <span style={{ color: TOKEN_COLOR[token.kind] }}>{token.text}</span>
      {renderTrailingComma(context.isLast)}
    </div>
  )
}

function renderEmptyContainerLine(isArray: boolean, context: NodeContext) {
  return (
    <div className={LINE_CLASS}>
      {renderKeyPrefix(context.key)}
      <span className={PUNCTUATION_CLASS}>{isArray ? "[]" : "{}"}</span>
      {renderTrailingComma(context.isLast)}
    </div>
  )
}

function childContext(
  parent: NodeContext,
  entry: JsonEntry,
  index: number,
  isLast: boolean
): NodeContext {
  // Quoted keys keep distinct nodes on distinct paths, e.g. {"a/b": 1} versus {"a": {"b": 2}}.
  const segment = entry.key === undefined ? index : JSON.stringify(entry.key)
  return {
    path: `${parent.path}/${segment}`,
    key: entry.key,
    depth: parent.depth + 1,
    isLast,
    open: parent.open,
    setNodeOpen: parent.setNodeOpen,
    defaultExpandedDepth: parent.defaultExpandedDepth,
  }
}

function renderContainerNode(entries: readonly JsonEntry[], isArray: boolean, context: NodeContext) {
  const open = context.open[context.path] ?? context.depth < context.defaultExpandedDepth
  return (
    <div className={LINE_CLASS}>
      <details
        open={open}
        onToggle={(event) => context.setNodeOpen(context.path, event.currentTarget.open)}
        className={LINE_CLASS}
      >
        <summary
          className={SUMMARY_CLASS}
          onClick={(event) => {
            // Native summary activation moves the DOM out from under the lazy-mount state.
            event.preventDefault()
            context.setNodeOpen(context.path, !open)
          }}
        >
          {renderKeyPrefix(context.key)}
          <span className={PUNCTUATION_CLASS}>{isArray ? "[" : "{"}</span>
          <span className="ml-2 text-[var(--muted)]">{countHint(entries.length, isArray)}</span>
        </summary>
        {/* children mount on first open only, which bounds the DOM for large payloads */}
        {open && (
          <div className={CHILD_BLOCK_CLASS}>
            {entries.map((entry, index) => (
              <div key={entry.key ?? index} className={LINE_CLASS}>
                {renderJsonNode(
                  entry.value,
                  childContext(context, entry, index, index === entries.length - 1)
                )}
              </div>
            ))}
          </div>
        )}
      </details>
      <div className={LINE_CLASS}>
        <span className={PUNCTUATION_CLASS}>{isArray ? "]" : "}"}</span>
        {renderTrailingComma(context.isLast)}
      </div>
    </div>
  )
}

function renderJsonNode(value: unknown, context: NodeContext) {
  if (!isContainer(value)) return renderScalarLine(value, context)
  const entries = containerEntries(value)
  if (entries.length === 0) return renderEmptyContainerLine(Array.isArray(value), context)
  return renderContainerNode(entries, Array.isArray(value), context)
}

export function JsonViewer({
  value,
  ariaLabel,
  defaultExpandedDepth = 1,
  className,
}: JsonViewerProps) {
  // Every hook lives here; nested nodes are plain render calls, so no second component is needed.
  const [expanded, setExpanded] = useState<Readonly<Record<string, boolean | undefined>>>({})

  const rootContext: NodeContext = {
    path: "root",
    depth: 0,
    isLast: true,
    open: expanded,
    setNodeOpen: (path, next) =>
      setExpanded((previous) => (previous[path] === next ? previous : { ...previous, [path]: next })),
    defaultExpandedDepth,
  }

  return (
    <div role="group" aria-label={ariaLabel} className={cn(WRAPPER_CLASS, className)}>
      {renderJsonNode(value, rootContext)}
    </div>
  )
}
