import { motion, useInView, useReducedMotion } from "motion/react"
import { useRef, type ReactNode } from "react"

const EASE = [0.22, 1, 0.36, 1] as const

export function Reveal({
  children,
  delay = 0,
  className,
}: {
  children: ReactNode
  delay?: number
  className?: string
}) {
  const reduced = useReducedMotion()
  if (reduced) return <div className={className}>{children}</div>
  return (
    <motion.div
      className={className}
      initial={{ opacity: 0, y: 12 }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, margin: "-12% 0px" }}
      transition={{ duration: 0.5, ease: EASE, delay }}
    >
      {children}
    </motion.div>
  )
}

/** Adds `revealed` to className once the element scrolls into view (or
 * immediately under reduced motion), so CSS can run enter transitions. */
export function Revealed({
  children,
  className,
}: {
  children: ReactNode
  className?: string
}) {
  const ref = useRef<HTMLDivElement>(null)
  const reduced = useReducedMotion()
  const inView = useInView(ref, { once: true, margin: "-15% 0px" })
  const cls = `${className ?? ""}${inView || reduced ? " revealed" : ""}`.trim()
  return (
    <div ref={ref} className={cls || undefined}>
      {children}
    </div>
  )
}
