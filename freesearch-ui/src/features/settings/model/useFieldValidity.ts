import { useCallback, useState } from "react"

export interface FieldValidity {
  /** Ids of the fields whose input is out of range or not a number. */
  invalid: ReadonlySet<string>
  setValidity: (fieldId: string, valid: boolean) => void
  clear: () => void
}

/**
 * Which settings inputs currently hold a value the draft cannot take. An
 * invalid input keeps the last valid draft value, so Save must refuse while
 * any input is invalid instead of writing a value the user no longer sees.
 */
export function useFieldValidity(): FieldValidity {
  const [invalid, setInvalid] = useState<ReadonlySet<string>>(() => new Set())

  const setValidity = useCallback((fieldId: string, valid: boolean) => {
    setInvalid((previous) => {
      if (previous.has(fieldId) === !valid) return previous
      const next = new Set(previous)
      if (valid) next.delete(fieldId)
      else next.add(fieldId)
      return next
    })
  }, [])

  const clear = useCallback(() => setInvalid(new Set()), [])

  return { invalid, setValidity, clear }
}
