import { useEffect, useRef, useState } from "react"
import type { KeyboardEvent, ReactNode } from "react"
import { createPortal } from "react-dom"
import { ChevronDown } from "lucide-react"
import { cn } from "cn"
import { SelectList } from "./SelectList"
import { keyEffect } from "./selectKeys"
import { selectRow } from "./selectRow"
import type { SelectOption, SelectOptionState } from "./selectTypes"
import { useListPlacement } from "./useListPlacement"

export type { SelectOption, SelectOptionState } from "./selectTypes"

export interface SelectProps {
  id?: string
  testId?: string
  value: string
  options: SelectOption[]
  onValueChange: (value: string) => void
  /** The trigger content of one value; defaults to the option icon and label. */
  renderValue?: (value: string) => ReactNode
  /** The popup row of one option; defaults to the option icon, label and description. */
  renderOption?: (option: SelectOption, state: SelectOptionState) => ReactNode
  /** Shown in the trigger while the value matches no option. */
  placeholder?: string
  disabled?: boolean
  invalid?: boolean
  ariaLabel?: string
  ariaDescribedBy?: string
  /** Trigger classes; defaults to the shared form-control look. */
  className?: string
  /** Align a non-dialog popup to the end of its trigger. */
  align?: "start" | "end"
}

/** The trigger content: the caller's renderer, else the shown option, else the placeholder. */
function triggerContent(props: SelectProps): ReactNode {
  const { value, options, renderValue, placeholder } = props
  if (renderValue !== undefined) return renderValue(value)
  const shown = options.find((option) => option.value === value)
  if (shown !== undefined) return selectRow(shown)
  return <span className="truncate text-[var(--muted)]">{placeholder ?? value}</span>
}

/** Open state, keyboard cursor and outside-click closing of one select. */
function useSelectState(options: readonly SelectOption[], value: string) {
  const [open, setOpen] = useState(false)
  const [active, setActive] = useState(0)
  const rootRef = useRef<HTMLDivElement>(null)
  const listRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!open) return
    function onOutsideDown(event: MouseEvent): void {
      const target = event.target as Node
      if (rootRef.current?.contains(target) || listRef.current?.contains(target)) return
      setOpen(false)
    }
    document.addEventListener("mousedown", onOutsideDown)
    return () => document.removeEventListener("mousedown", onOutsideDown)
  }, [open])
  /** Open the list at the shown value, so the first move starts from it. */
  function openAtValue(): void {
    const index = options.findIndex((option) => option.value === value)
    const firstEnabled = options.findIndex((option) => option.disabled !== true)
    setActive(index < 0 ? Math.max(0, firstEnabled) : index)
    setOpen(true)
  }
  return { open, setOpen, active, setActive, rootRef, listRef, openAtValue }
}

/**
 * One select with rich rows.
 *
 * The trigger and every option render caller content, so a caller can show a
 * logo and a name. The shown value takes strong text and a trailing check,
 * and the keyboard cursor takes the raised surface; blue stays for focus.
 * The control keeps the combobox roles, the `aria-selected` state, and full
 * keyboard access, and it closes on a click outside.
 */
export function Select(props: SelectProps): ReactNode {
  const { id, testId, value, options, onValueChange, renderOption, disabled, invalid, className } = props
  const { open, setOpen, active, setActive, rootRef, listRef, openAtValue } = useSelectState(options, value)
  const triggerRef = useRef<HTMLButtonElement>(null)
  const placement = useListPlacement(open, triggerRef)
  const listId = (id ?? "select") + "-list"

  function commit(index: number): void {
    const option = options[index]
    if (option === undefined || option.disabled === true) return
    onValueChange(option.value)
    setOpen(false)
    triggerRef.current?.focus()
  }

  function onKeyDown(event: KeyboardEvent<HTMLButtonElement>): void {
    const enabled = options.map((option) => option.disabled !== true)
    const effect = keyEffect(event.key, open, active, enabled)
    if (effect === null) return
    event.preventDefault()
    // An open list inside a dialog closes alone; Escape must not close the dialog too.
    if (open && event.key === "Escape") event.stopPropagation()
    if (effect.open && !open) return openAtValue()
    setOpen(effect.open)
    setActive(effect.active)
    if (effect.choose) commit(active)
  }

  const list = open && (
    <SelectList
      listRef={listRef}
      listId={listId}
      labelledBy={id}
      options={options}
      value={value}
      active={active}
      style={placement?.style}
      onActivate={setActive}
      onCommit={commit}
      renderOption={renderOption}
      align={props.align}
    />
  )

  return (
    <div ref={rootRef} className="relative">
      <button
        ref={triggerRef}
        type="button"
        id={id}
        data-testid={testId}
        disabled={disabled}
        role="combobox"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={open ? listId : undefined}
        aria-activedescendant={open ? listId + "-" + active : undefined}
        aria-label={props.ariaLabel}
        aria-describedby={props.ariaDescribedBy}
        aria-invalid={invalid === true ? true : undefined}
        className={cn(className ?? "fs-select-trigger", "flex items-center justify-between gap-2 text-left")}
        onClick={() => (open ? setOpen(false) : openAtValue())}
        onKeyDown={onKeyDown}
      >
        {triggerContent(props)}
        <ChevronDown className="size-4 shrink-0 text-[var(--muted)]" aria-hidden="true" />
      </button>
      {placement !== null && list ? createPortal(list, placement.host) : list}
    </div>
  )
}
