/**
 * Class names of every popup menu (row actions, project switcher, account
 * menu), so menu rows share one height, padding, hover and danger tone.
 */
export const MENU_ITEM_BASE =
  "flex h-8 w-full items-center gap-2 rounded-md px-2 text-left text-[13px] transition-colors hover:bg-[var(--raised)] focus-visible:bg-[var(--raised)] focus-visible:outline-none disabled:pointer-events-none disabled:opacity-50 [&_svg]:size-4 [&_svg]:shrink-0"
export const MENU_ITEM_CLASS = `${MENU_ITEM_BASE} text-[var(--text)] hover:text-[var(--text-strong)]`
export const MENU_ITEM_DANGER_CLASS = `${MENU_ITEM_BASE} text-[var(--status-danger)]`
export const MENU_SEPARATOR_CLASS = "my-1 h-px bg-[var(--hairline)]"
export const MENU_TRIGGER_ICON_CLASS =
  "grid size-7 place-items-center rounded-md text-[var(--muted)] transition-colors hover:bg-[var(--raised)] hover:text-[var(--text-strong)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--signal)] disabled:opacity-50 aria-expanded:bg-[var(--raised)] aria-expanded:text-[var(--text-strong)]"
