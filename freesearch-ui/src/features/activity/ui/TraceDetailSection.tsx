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
    <section className="space-y-2">
      <h4 className="text-[12px] text-[var(--muted)]">{title}</h4>
      {children}
    </section>
  )
}
