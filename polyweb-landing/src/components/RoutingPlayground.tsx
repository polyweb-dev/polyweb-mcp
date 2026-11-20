import { useEffect, useRef, useState } from "react"
import { AnimatePresence, motion, useReducedMotion } from "motion/react"

import { PROVIDERS, pickRandom } from "../providers"

const EASE = [0.22, 1, 0.36, 1] as const

type State = "up" | "limited" | "quota" | "down"

const STATES: { id: State; label: string }[] = [
  { id: "up", label: "Healthy" },
  { id: "limited", label: "Rate-limited" },
  { id: "quota", label: "Out of quota" },
  { id: "down", label: "Down" },
]

const LINEUP = pickRandom(
  PROVIDERS.filter((p) => p.search),
  4
)

interface TraceRow {
  id: string
  name: string
  src: string
  outcome: string
  tone: "green" | "amber" | "gray" | "red"
}

function route(states: Record<string, State>): {
  rows: TraceRow[]
  ok: boolean
} {
  const rows: TraceRow[] = []
  for (const p of LINEUP) {
    const s = states[p.id]
    const base = { id: p.id, name: p.name, src: p.src }
    if (s === "quota") {
      rows.push({ ...base, outcome: "Skipped · out of quota", tone: "gray" })
    } else if (s === "down") {
      rows.push({ ...base, outcome: "Skipped · down", tone: "gray" })
    } else if (s === "limited") {
      rows.push({ ...base, outcome: "429 · fell back", tone: "amber" })
    } else {
      const ms = 380 + ((p.id.length * 97) % 520)
      rows.push({ ...base, outcome: `Answered · ${ms} ms`, tone: "green" })
      return { rows, ok: true }
    }
  }
  return { rows, ok: false }
}

/** A small hands-on demo: switch providers between healthy, rate-limited,
 * out of quota and down, send a request, and watch the routing trace. */
export function RoutingPlayground() {
  const reduced = useReducedMotion()
  const [states, setStates] = useState<Record<string, State>>(() =>
    Object.fromEntries(
      LINEUP.map((p, i) => [p.id, i === 0 ? "limited" : "up"] as const)
    )
  )
  const [run, setRun] = useState(0)
  const [shown, setShown] = useState(0)
  const result = route(states)
  const timer = useRef<number | undefined>(undefined)

  useEffect(() => () => window.clearInterval(timer.current), [])

  // Send a request: reveal the trace rows one by one.
  const send = () => {
    window.clearInterval(timer.current)
    // The trace never has more rows than the lineup; slicing handles the rest.
    const total = LINEUP.length
    setRun((r) => r + 1)
    if (reduced) {
      setShown(total)
      return
    }
    setShown(1)
    let n = 1
    timer.current = window.setInterval(() => {
      n += 1
      setShown(n)
      if (n >= total) window.clearInterval(timer.current)
    }, 320)
  }

  const cycle = (id: string) => {
    window.clearInterval(timer.current)
    setStates((prev) => {
      const i = STATES.findIndex((s) => s.id === prev[id])
      return { ...prev, [id]: STATES[(i + 1) % STATES.length].id }
    })
    setShown(0)
    setRun(0)
  }

  const done = run > 0 && shown >= result.rows.length
  const visible = run > 0 ? result.rows.slice(0, shown) : []

  return (
    <div className="play">
      <div className="play-controls">
        <p className="play-label">
          Provider order <span>· tap to change status</span>
        </p>
        <ol className="play-lineup">
          {LINEUP.map((p, i) => {
            const s = states[p.id]
            const label = STATES.find((x) => x.id === s)!.label
            return (
              <li key={p.id}>
                <button
                  type="button"
                  className={`play-chip play-${s}`}
                  onClick={() => cycle(p.id)}
                  aria-label={`${p.name}, ${label}. Change status`}
                >
                  <span className="play-chip-n">{i + 1}</span>
                  <img src={p.src} alt="" />
                  <span className="play-chip-name">{p.name}</span>
                  <span className="play-chip-state">
                    <span className="play-dot" aria-hidden="true" />
                    {label}
                  </span>
                </button>
              </li>
            )
          })}
        </ol>
        <button
          type="button"
          className="button button-primary button-pill play-send"
          onClick={send}
        >
          Send request
        </button>
      </div>

      <div className="play-trace" aria-live="polite">
        <p className="play-req">
          <span className="panel-method">POST</span> /search{" "}
          <span className="play-req-q">"latest climate research"</span>
        </p>
        {run === 0 ? (
          <p className="play-empty">
            Set a few providers to fail, then send a request.
          </p>
        ) : (
          <ol className="play-rows" key={run}>
            <AnimatePresence initial={!reduced}>
              {visible.map((r, i) => (
                <motion.li
                  key={r.id}
                  className="play-row"
                  initial={reduced ? false : { opacity: 0, y: 6 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.3, ease: EASE }}
                >
                  <span className="play-row-n">{i + 1}</span>
                  <img src={r.src} alt="" />
                  <span className="play-row-name">{r.name}</span>
                  <span className={`tag-pill tag-${r.tone}`}>{r.outcome}</span>
                </motion.li>
              ))}
            </AnimatePresence>
          </ol>
        )}
        {done && (
          <motion.p
            className={`play-result${result.ok ? "" : " play-result-fail"}`}
            initial={reduced ? false : { opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ duration: 0.3 }}
          >
            {result.ok
              ? `Answered by ${result.rows[result.rows.length - 1].name}. Your agent never saw the failures.`
              : "No provider available · 503 with the full trace"}
          </motion.p>
        )}
      </div>
    </div>
  )
}
