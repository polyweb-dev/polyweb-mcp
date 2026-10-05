import type { ReactNode } from "react"

/** Labelled content block inside the detail dialog (query in, results out). */
export function TraceDetailSection({
  title,
  children,
}: {
  title: string
  children: ReactNode
}) {
  return (
    <section className="flex min-w-0 items-center rounded-md border border-[var(--border-subtle)] bg-[var(--surface)] px-3 py-2">
      <div className="flex min-w-0 flex-1 items-baseline gap-3">
        <h4 className="m-0 shrink-0 text-[11px] leading-[18px] text-[var(--muted)]">{title}</h4>
        <div className="min-w-0 flex-1">{children}</div>
      </div>
    </section>
  )
}
