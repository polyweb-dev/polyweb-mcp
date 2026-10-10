import { useEffect, useRef, useState } from "react"
import type { KeyboardEvent, ReactNode } from "react"
import { ChevronDown } from "lucide-react"
import { cn } from "cn"

export interface SelectOption {
  value: string
  label: string
}

/** The state of one row, which tells the caller how to present its content. */
export interface SelectOptionState {
  /** The shown value of the control. */
  selected: boolean
  /** The row of the keyboard cursor. */
  active: boolean
}

export interface SelectProps {
  id?: string
  testId?: string
  value: string
  options: SelectOption[]
  onValueChange: (value: string) => void
  /** The trigger content of one value: the caller renders its own identity. */
  renderValue: (value: string) => ReactNode
  /** The popup row of one option: the caller renders its own identity. */
  renderOption: (option: SelectOption, state: SelectOptionState) => ReactNode
  disabled?: boolean
  className?: string
}

/** The state after one key press: the open flag, the active index, and a choice. */
interface KeyEffect {
  open: boolean
  active: number
  choose: boolean
}

/**
 * The popup grows to its widest entry, so a long label never truncates and the
 * list shows no horizontal scrollbar. The height cap keeps an extreme list on
 * the screen; a normal list shows every entry without a scrollbar.
 */
const LIST =
  "absolute left-0 right-0 z-50 mt-1 max-h-[70vh] w-max min-w-full overflow-y-auto rounded border border-[var(--border-subtle)] bg-[var(--elevated)] p-1 shadow-lg"
const ITEM = "flex cursor-default items-center gap-2 rounded px-2 py-1.5 text-[13px] text-[var(--text)]"
const ITEM_ACTIVE = "bg-[var(--surface)]"
const ITEM_SELECTED = "bg-[var(--signal)] text-white"

/** The row style: the shown value wins over the keyboard cursor. */
function rowClass(selected: boolean, active: boolean): string {
  if (selected) return ITEM_SELECTED
  return active ? ITEM_ACTIVE : ""
}

/** The effect of one move key on an open list: the arrows, Home, and End. */
function moveEffect(key: string, active: number, count: number): KeyEffect | null {
  if (key === "ArrowDown" || key === "ArrowUp") {
    const step = key === "ArrowDown" ? 1 : -1
    return { open: true, active: (active + step + count) % count, choose: false }
  }
  if (key === "Home") return { open: true, active: 0, choose: false }
  if (key === "End") return { open: true, active: count - 1, choose: false }
  return null
}

/**
 * The effect of one key press on the list. A key without an effect yields null.
 *
 * A closed list opens on the arrows, Enter, and Space. An open list moves on
 * the arrows, Home, and End, chooses on Enter and Space, and closes on Escape
 * and Tab.
 */
function keyEffect(key: string, open: boolean, active: number, count: number): KeyEffect | null {
  if (!open) {
    if (key === "ArrowDown" || key === "ArrowUp" || key === "Enter" || key === " ") {
      return { open: true, active, choose: false }
    }
    return null
  }
  const move = moveEffect(key, active, count)
  if (move !== null) return move
  if (key === "Enter" || key === " ") return { open: false, active, choose: true }
  if (key === "Escape" || key === "Tab") return { open: false, active, choose: false }
  return null
}

/**
 * One select with rich rows.
 *
 * The trigger and every option render caller content, so a caller can show a
 * logo and a name. A row holds no check gutter: the shown value takes the
 * signal background and white text, and the keyboard cursor takes the surface
 * tint. The control keeps the combobox roles, the `aria-selected` state, and
 * full keyboard access, and it closes on a click outside.
 */
export function Select({
  id,
  testId,
  value,
  options,
  onValueChange,
  renderValue,
  renderOption,
  disabled,
  className,
}: SelectProps): ReactNode {
  const [open, setOpen] = useState(false)
  const [active, setActive] = useState(0)
  const rootRef = useRef<HTMLDivElement>(null)
  const listId = (id ?? "select") + "-list"

  useEffect(() => {
    if (!open) return
    function onOutsideDown(event: MouseEvent): void {
      const root = rootRef.current
      if (root !== null && !root.contains(event.target as Node)) setOpen(false)
    }
    document.addEventListener("mousedown", onOutsideDown)
    return () => document.removeEventListener("mousedown", onOutsideDown)
  }, [open])

  /** Open the list at the shown value, so the first move starts from it. */
  function openAtValue(): void {
    const index = options.findIndex((option) => option.value === value)
    setActive(index < 0 ? 0 : index)
    setOpen(true)
  }

  function commit(index: number): void {
    const option = options[index]
    if (option === undefined) return
    onValueChange(option.value)
    setOpen(false)
  }

  function onKeyDown(event: KeyboardEvent<HTMLButtonElement>): void {
    const effect = keyEffect(event.key, open, active, options.length)
    if (effect === null) return
    event.preventDefault()
    if (effect.open && !open) {
      openAtValue()
      return
    }
    setOpen(effect.open)
    setActive(effect.active)
    if (effect.choose) commit(active)
  }

  return (
    <div ref={rootRef} className="relative">
      <button
        type="button"
        id={id}
        data-testid={testId}
        disabled={disabled}
        role="combobox"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={open ? listId : undefined}
        aria-activedescendant={open ? listId + "-" + active : undefined}
        className={cn(className, "flex items-center justify-between gap-2 text-left")}
        onClick={() => (open ? setOpen(false) : openAtValue())}
        onKeyDown={onKeyDown}
      >
        {renderValue(value)}
        <ChevronDown className="size-4 shrink-0 text-[var(--muted)]" aria-hidden="true" />
      </button>
      {open && (
        <div id={listId} role="listbox" aria-labelledby={id} className={LIST}>
          {options.map((option, index) => (
            <div
              key={option.value}
              id={listId + "-" + index}
              role="option"
              aria-selected={option.value === value}
              className={cn(ITEM, rowClass(option.value === value, index === active))}
              onMouseEnter={() => setActive(index)}
              onClick={() => commit(index)}
            >
              {renderOption(option, {
                selected: option.value === value,
                active: index === active,
              })}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
