import type { CSSProperties, ReactNode, RefObject } from "react"
import { Check } from "lucide-react"
import { cn } from "cn"
import { selectRow } from "./selectRow"
import type { SelectOption, SelectOptionState } from "./selectTypes"

/**
 * The popup grows to its widest entry, so a long label never truncates and the
 * list shows no horizontal scrollbar. The height cap keeps an extreme list on
 * the screen; a normal list shows every entry without a scrollbar.
 */
const LIST =
  "z-50 w-max min-w-full overflow-y-auto rounded border border-[var(--border-subtle)] bg-[var(--elevated)] p-1 shadow-lg"
const ITEM = "flex cursor-default items-center justify-between gap-3 rounded px-2 py-1.5 text-[13px] text-[var(--text)]"
const ITEM_ACTIVE = "bg-[var(--raised)]"
const ITEM_SELECTED = "text-[var(--text-strong)]"
const ITEM_DISABLED = "opacity-45"

/** The row style: the keyboard cursor takes the raised surface; the shown value takes strong text and a check. */
function rowClass(selected: boolean, active: boolean): string {
  return cn(active && ITEM_ACTIVE, selected && ITEM_SELECTED)
}

export interface SelectListProps {
  listRef: RefObject<HTMLDivElement | null>
  listId: string
  labelledBy: string | undefined
  options: readonly SelectOption[]
  value: string
  active: number
  /** Fixed placement inside a dialog; `undefined` renders under the trigger. */
  style: CSSProperties | undefined
  onActivate: (index: number) => void
  onCommit: (index: number) => void
  renderOption?: (option: SelectOption, state: SelectOptionState) => ReactNode
  align?: "start" | "end"
}

/** The listbox of one `Select`: every option row with its selected, cursor and disabled state. */
export function SelectList({
  listRef,
  listId,
  labelledBy,
  options,
  value,
  active,
  style,
  onActivate,
  onCommit,
  renderOption,
  align,
}: SelectListProps) {
  return (
    <div
      ref={listRef}
      id={listId}
      role="listbox"
      aria-labelledby={labelledBy}
      className={cn(LIST, style === undefined && (align === "end"
        ? "absolute right-0 mt-1 max-h-[70vh] max-w-[calc(100vw-2rem)]"
        : "absolute right-0 left-0 mt-1 max-h-[70vh]"))}
      style={style}
    >
      {options.map((option, index) => {
        const selected = option.value === value
        const disabled = option.disabled === true
        return (
          <div
            key={option.value}
            id={listId + "-" + index}
            role="option"
            aria-selected={selected}
            aria-disabled={disabled ? true : undefined}
            className={cn(ITEM, rowClass(selected, index === active), disabled && ITEM_DISABLED)}
            onMouseEnter={() => !disabled && onActivate(index)}
            onClick={() => onCommit(index)}
          >
            {renderOption !== undefined
              ? renderOption(option, { selected, active: index === active })
              : selectRow(option)}
            <Check
              aria-hidden="true"
              className={cn("size-3.5 shrink-0 text-[var(--text-strong)]", !selected && "invisible")}
            />
          </div>
        )
      })}
    </div>
  )
}
