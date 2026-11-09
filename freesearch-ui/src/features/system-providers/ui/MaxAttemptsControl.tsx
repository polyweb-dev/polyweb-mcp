import { Minus, Plus } from "lucide-react"
import { Button } from "@/shared/ui/button"

const MIN_ATTEMPTS = 1
const MAX_ATTEMPTS = 10

interface MaxAttemptsControlProps {
  value: number
  onChange: (next: number) => void
}

/** Stepper for the routing hop limit, bounded to what project settings also accept. */
export function MaxAttemptsControl({ value, onChange }: MaxAttemptsControlProps) {
  const set = (next: number) => onChange(Math.min(MAX_ATTEMPTS, Math.max(MIN_ATTEMPTS, next)))
  return (
    <div className="flex items-center gap-2">
      <Button
        type="button"
        variant="outline"
        size="icon"
        aria-label="Decrease max attempts"
        disabled={value <= MIN_ATTEMPTS}
        onClick={() => set(value - 1)}
      >
        <Minus aria-hidden="true" />
      </Button>
      <output aria-live="polite" className="min-w-8 text-center text-[13px] text-[var(--text-strong)] tnum">
        {value}
      </output>
      <Button
        type="button"
        variant="outline"
        size="icon"
        aria-label="Increase max attempts"
        disabled={value >= MAX_ATTEMPTS}
        onClick={() => set(value + 1)}
      >
        <Plus aria-hidden="true" />
      </Button>
    </div>
  )
}
