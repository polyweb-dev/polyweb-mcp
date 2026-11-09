/** The state after one key press: the open flag, the active index, and a choice. */
export interface KeyEffect {
  open: boolean
  active: number
  choose: boolean
}

/** Next enabled index from `start` in `step` direction, wrapping; `start` when none is enabled. */
export function nextEnabled(start: number, step: number, enabled: readonly boolean[]): number {
  const count = enabled.length
  for (let offset = 1; offset <= count; offset++) {
    const index = (start + step * offset + count * offset) % count
    if (enabled[index]) return index
  }
  return start
}

/** The effect of one move key on an open list: the arrows, Home, and End. */
function moveEffect(key: string, active: number, enabled: readonly boolean[]): KeyEffect | null {
  if (key === "ArrowDown" || key === "ArrowUp") {
    return { open: true, active: nextEnabled(active, key === "ArrowDown" ? 1 : -1, enabled), choose: false }
  }
  if (key === "Home") return { open: true, active: nextEnabled(-1, 1, enabled), choose: false }
  if (key === "End") return { open: true, active: nextEnabled(enabled.length, -1, enabled), choose: false }
  return null
}

/**
 * The effect of one key press on the list. A key without an effect yields null.
 *
 * A closed list opens on the arrows, Enter, and Space. An open list moves on
 * the arrows, Home, and End over enabled rows, chooses on Enter and Space, and
 * closes on Escape and Tab.
 */
export function keyEffect(
  key: string,
  open: boolean,
  active: number,
  enabled: readonly boolean[]
): KeyEffect | null {
  if (!open) {
    if (key === "ArrowDown" || key === "ArrowUp" || key === "Enter" || key === " ") {
      return { open: true, active, choose: false }
    }
    return null
  }
  const move = moveEffect(key, active, enabled)
  if (move !== null) return move
  if (key === "Enter" || key === " ") return { open: false, active, choose: true }
  if (key === "Escape" || key === "Tab") return { open: false, active, choose: false }
  return null
}
