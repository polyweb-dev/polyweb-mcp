import { useState } from "react"
import { CalendarDays, ChevronLeft, ChevronRight } from "lucide-react"
import { Button } from "./button"
import { Popover, PopoverContent, PopoverTrigger } from "./popover"
import { TextField } from "./TextField"

interface DateFieldProps {
  id: string
  label: string
  value: string
  onChange: (value: string) => void
  disabled?: boolean
  error?: string | null
  hint?: string
  placeholder?: string
  className?: string
}

function isoDate(year: number, month: number, day: number): string {
  return `${year}-${String(month + 1).padStart(2, "0")}-${String(day).padStart(2, "0")}`
}

function initialMonth(value: string): Date {
  const match = /^(\d{4})-(\d{2})-\d{2}$/.exec(value)
  if (match && Number(match[2]) >= 1 && Number(match[2]) <= 12) {
    return new Date(Number(match[1]), Number(match[2]) - 1, 1)
  }
  const today = new Date()
  return new Date(today.getFullYear(), today.getMonth(), 1)
}

export function DateField({ id, label, value, onChange, disabled, error, hint, placeholder, className }: DateFieldProps) {
  const [open, setOpen] = useState(false)
  const [month, setMonth] = useState(() => initialMonth(value))
  const year = month.getFullYear()
  const monthIndex = month.getMonth()
  const firstDay = new Date(year, monthIndex, 1).getDay()
  const days = new Date(year, monthIndex + 1, 0).getDate()
  const monthLabel = month.toLocaleDateString("en-US", { month: "long", year: "numeric" })

  return <div className={className}>
    <div className="flex items-start gap-2">
      <div className="min-w-0 flex-1">
        <TextField id={id} label={label} type="text" value={value} onChange={onChange}
          disabled={disabled} error={error} hint={hint} placeholder={placeholder} />
      </div>
      <Popover open={open} onOpenChange={(next) => {
        if (next) setMonth(initialMonth(value))
        setOpen(next)
      }}>
        <PopoverTrigger
          disabled={disabled}
          aria-label={`Choose ${label.toLowerCase()}`}
          render={<Button type="button" variant="outline" size="default" className="mt-6" />}
        ><CalendarDays className="size-4" aria-hidden="true" /></PopoverTrigger>
        {open && <PopoverContent align="start" className="w-64">
          <div className="mb-3 flex items-center justify-between">
            <Button type="button" variant="outline" size="sm" aria-label="Previous month"
              onClick={() => setMonth(new Date(year, monthIndex - 1, 1))}>
              <ChevronLeft className="size-4" aria-hidden="true" />
            </Button>
            <span aria-live="polite" className="font-semibold">{monthLabel}</span>
            <Button type="button" variant="outline" size="sm" aria-label="Next month"
              onClick={() => setMonth(new Date(year, monthIndex + 1, 1))}>
              <ChevronRight className="size-4" aria-hidden="true" />
            </Button>
          </div>
          <div className="grid grid-cols-7 gap-1 text-center">
            {["S", "M", "T", "W", "T", "F", "S"].map((day, index) =>
              <span key={index} className="text-[var(--muted)]">{day}</span>)}
            {Array.from({ length: firstDay }, (_, index) => <span key={`empty-${index}`} />)}
            {Array.from({ length: days }, (_, index) => {
              const day = index + 1
              const date = isoDate(year, monthIndex, day)
              return <button key={date} type="button" aria-label={`${monthLabel} ${day}`}
                aria-pressed={date === value}
                className="rounded p-1 hover:bg-[var(--surface)] focus-visible:outline focus-visible:outline-[var(--signal)] aria-pressed:bg-[var(--signal)]"
                onClick={() => { onChange(date); setOpen(false) }}>{day}</button>
            })}
          </div>
        </PopoverContent>}
      </Popover>
    </div>
  </div>
}
