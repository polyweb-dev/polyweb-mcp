/** Ids a control passes to `aria-describedby` for the hint and error a `Field` renders. */
export function fieldDescribedBy(id: string, hint: unknown, error: unknown): string | undefined {
  if (error) return `${id}-error`
  return hint ? `${id}-hint` : undefined
}
