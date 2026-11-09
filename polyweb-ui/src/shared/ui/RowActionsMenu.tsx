import { useState } from "react"
import { MoreHorizontal } from "lucide-react"
import { MENU_ITEM_CLASS, MENU_ITEM_DANGER_CLASS, MENU_TRIGGER_ICON_CLASS } from "./menuStyles"
import { Popover, PopoverContent, PopoverTrigger } from "./popover"

export interface RowAction {
  key: string
  label: string
  onSelect: () => void
  /** Destructive items sit last, in the danger tone. */
  danger?: boolean
  disabled?: boolean
  testId?: string
}

export interface RowActionsMenuProps {
  /** Accessible name of the trigger, such as `Actions for dev-exa`. */
  label: string
  actions: readonly RowAction[]
  disabled?: boolean
}

/**
 * The one row-action pattern of every table: a quiet `…` trigger that opens a
 * short menu. An item closes the menu before it runs, so a confirmation
 * dialog it opens takes the focus.
 */
export function RowActionsMenu({ label, actions, disabled = false }: RowActionsMenuProps) {
  const [open, setOpen] = useState(false)
  if (actions.length === 0) return null
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger
        aria-label={label}
        disabled={disabled}
        className={MENU_TRIGGER_ICON_CLASS}
      >
        <MoreHorizontal aria-hidden="true" className="size-4" />
      </PopoverTrigger>
      {open && (
        <PopoverContent align="end" sideOffset={4} className="w-52 p-1">
          {actions.map((action) => (
            <button
              key={action.key}
              type="button"
              disabled={action.disabled}
              data-testid={action.testId}
              className={action.danger === true ? MENU_ITEM_DANGER_CLASS : MENU_ITEM_CLASS}
              onClick={() => {
                setOpen(false)
                action.onSelect()
              }}
            >
              {action.label}
            </button>
          ))}
        </PopoverContent>
      )}
    </Popover>
  )
}
