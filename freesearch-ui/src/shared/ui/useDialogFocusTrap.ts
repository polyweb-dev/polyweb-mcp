import { useEffect, useRef } from "react"

/** Everything a keyboard user can land on inside the dialog. */
const FOCUSABLE_SELECTOR = [
  "a[href]",
  "button:not([disabled])",
  "input:not([disabled])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  '[tabindex]:not([tabindex="-1"])',
].join(",")

/** Visible dialogs put the first control within a frame or two. */
const ENTRY_ATTEMPTS = 12
const ENTRY_RETRY_MS = 16

/** A hidden or inert control is not a tab stop, however focusable its tag is. */
function isReachable(element: HTMLElement): boolean {
  return element.getClientRects().length > 0 && !element.closest("[inert]")
}

function focusablesIn(container: HTMLElement): HTMLElement[] {
  return Array.from(container.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR))
    .filter(isReachable)
    .filter((element) => element !== container)
}

/**
 * The control focus enters on open. The close button is skipped on purpose: it
 * is the one control a dialog renders before its body, so landing there would
 * skip past the content the user opened the dialog to read.
 */
function entryTarget(container: HTMLElement): HTMLElement | null {
  return focusablesIn(container).find((element) => element.dataset.slot !== "dialog-close") ?? null
}

/**
 * Wraps Tab at both ends of the dialog. The only way a background element is
 * the active one while the dialog is open is that focus escaped, and the
 * previously focused node is the dialog's trigger — so restoring to it is
 * exactly the pre-open state and the browser continues from there.
 */
function wrapTab(container: HTMLElement, backwards: boolean): void {
  const active = document.activeElement
  const inside = active instanceof HTMLElement && container.contains(active)
  if (!inside) {
    if (!backwards) (entryTarget(container) ?? container).focus()
    return
  }
  const elements = focusablesIn(container)
  const first = elements[0]
  const last = elements[elements.length - 1]
  if (first === undefined || last === undefined) return
  if (!backwards && active === last) first.focus()
  if (backwards && active === first) last.focus()
}

/**
 * Moves focus to the dialog's first control. The body's controls do not exist
 * on the frame the popup mounts, so this retries briefly; a timer rather than
 * `requestAnimationFrame` because frames do not run in a backgrounded
 * document, where the dialog is otherwise perfectly usable.
 */
function focusEntry(container: HTMLElement): number {
  const attempt = (remaining: number): number => {
    if (!document.contains(container)) return 0
    const target = entryTarget(container)
    if (target !== null) {
      target.focus()
      return 0
    }
    if (remaining <= 1) return 0
    return window.setTimeout(() => attempt(remaining - 1), ENTRY_RETRY_MS)
  }
  return attempt(ENTRY_ATTEMPTS)
}

/**
 * Keyboard containment for a modal dialog (APPROVED F7 scope): focus enters the
 * dialog when it opens and cannot be tabbed out to the page behind it.
 *
 * Returns a callback ref for the dialog element, because the dialog primitive
 * mounts its popup without the dialog body: the callback fires on the bare
 * popup, so the move to the content is retried until the body's controls
 * exist. Tab wrapping is installed once and reads the element through a ref, so
 * the listener survives every content re-render.
 *
 * Escape, the close button, and focus restoration to the trigger remain the
 * dialog primitive's responsibility.
 */
export function useDialogFocusTrap(): (node: HTMLElement | null) => void {
  const containerRef = useRef<HTMLElement | null>(null)
  const timerRef = useRef(0)
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      const container = containerRef.current
      if (event.key !== "Tab" || event.defaultPrevented || container === null) return
      wrapTab(container, event.shiftKey)
    }
    document.addEventListener("keydown", onKeyDown, true)
    return () => {
      document.removeEventListener("keydown", onKeyDown, true)
      window.clearTimeout(timerRef.current)
    }
  }, [])
  return (node) => {
    containerRef.current = node
    window.clearTimeout(timerRef.current)
    if (node === null) return
    timerRef.current = focusEntry(node)
  }
}
