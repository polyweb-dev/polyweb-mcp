/** Move an item to the target position without changing the input. */
export function reorderProviderPriority(ids: readonly string[], source: string, target: string): string[] {
  const from = ids.indexOf(source)
  const to = ids.indexOf(target)
  if (from < 0 || to < 0 || from === to) return [...ids]
  const result = [...ids]
  const [item] = result.splice(from, 1)
  if (item !== undefined) result.splice(to, 0, item)
  return result
}
