import { useRef } from "react"
import {
  motion,
  useMotionValue,
  useReducedMotion,
  useScroll,
  useTransform,
  type MotionValue,
} from "motion/react"

import { PROVIDERS, pickRandom } from "../providers"

const QUERY = "latest climate research"
// a search query only ever routes to search-capable providers
const CARDS = pickRandom(PROVIDERS.filter((p) => p.search), 3)
const RESULTS = [
  ["Global temperature record broken in 2026", "nature.com"],
  ["How cities adapt to a warming coastline", "reuters.com"],
  ["Ocean heat content hits a new high", "noaa.gov"],
]

function Head({
  progress,
  from,
  to,
  text,
}: {
  progress: MotionValue<number>
  from: number
  to: number
  text: string
}) {
  const opacity = useTransform(
    progress,
    [from, from + 0.03, to - 0.03, to],
    [0, 1, 1, to >= 1 ? 1 : 0]
  )
  const y = useTransform(progress, [from, from + 0.03], [24, 0])
  return (
    <motion.h2 className="scene-headline scene-head" style={{ opacity, y }}>
      {text}
    </motion.h2>
  )
}

function ProviderCard({
  progress,
  index,
}: {
  progress: MotionValue<number>
  index: number
}) {
  const { name, src } = CARDS[index]

  // unused card stays quiet until the scene settles
  const idleOn = useTransform(progress, [0.16, 0.22], [0, 1], { clamp: true })

  // Brave fails in phase b: shake + tint + "Rate limited"
  const shakeX = useTransform(
    progress,
    [0.42, 0.45, 0.48, 0.51, 0.54],
    index === 0 ? [0, -4, 4, -2, 0] : [0, 0, 0, 0, 0]
  )
  const failTint = useTransform(progress, [0.44, 0.54], [0, index === 0 ? 1 : 0], { clamp: true })
  const failLabel = useTransform(progress, [0.48, 0.56], [0, 1], { clamp: true })

  // Exa answers in phase c: accent border + "Answered"
  const answerOn = useTransform(progress, [0.62, 0.72], [0, index === 1 ? 1 : 0], { clamp: true })

  const idle = index === 2 ? "Not needed" : index === 0 ? "Rate limited" : "Answered"
  const stateOpacity = index === 0 ? failLabel : index === 1 ? answerOn : idleOn

  return (
    <motion.div className="provider-card" style={{ x: shakeX }}>
      <motion.div
        className="provider-card-fail"
        style={{ opacity: failTint }}
        aria-hidden="true"
      />
      <motion.div
        className="provider-card-answer"
        style={{ opacity: answerOn }}
        aria-hidden="true"
      />
      <img src={src} alt="" width={72} height={72} />
      <span className="provider-card-name">{name}</span>
      <motion.span
        className={`provider-card-state${index === 1 ? " state-ok" : " state-idle"}`}
        style={{ opacity: stateOpacity }}
      >
        {idle}
      </motion.span>
    </motion.div>
  )
}

function ResultCard({
  title,
  domain,
  reveal,
}: {
  title: string
  domain: string
  reveal: MotionValue<number>
}) {
  const y = useTransform(reveal, [0, 1], [28, 0])
  return (
    <motion.div className="result-card" style={{ opacity: reveal, y }}>
      <span className="result-title">{title}</span>
      <span className="result-domain">{domain}</span>
    </motion.div>
  )
}

export function RoutingScene() {
  const ref = useRef<HTMLDivElement>(null)
  const reduced = useReducedMotion()
  const { scrollYProgress } = useScroll({
    target: ref,
    offset: ["start start", "end end"],
  })
  const done = useMotionValue(1)
  const progress = reduced ? done : scrollYProgress

  // query bar types in at the start
  const typed = useTransform(progress, [0, 0.12], [0, QUERY.length], {
    clamp: true,
  })
  const queryText = useTransform(typed, (n) => QUERY.slice(0, Math.round(n)))

  // pulse: travels the track — reaches Brave mid-phase-b, then Exa mid-phase-c
  const pulseX = useTransform(
    progress,
    [0.34, 0.44, 0.56, 0.66],
    ["4%", "24%", "24%", "50%"]
  )
  const pulseOpacity = useTransform(
    progress,
    [0.3, 0.36, 0.66, 0.74],
    [0, 1, 1, 0]
  )

  // results cascade in late phase c
  const r1 = useTransform(progress, [0.7, 0.78], [0, 1], { clamp: true })
  const r2 = useTransform(progress, [0.76, 0.84], [0, 1], { clamp: true })
  const r3 = useTransform(progress, [0.82, 0.9], [0, 1], { clamp: true })
  const results = [r1, r2, r3]

  const finalCap = useTransform(progress, [0.9, 0.96], [0, 1], { clamp: true })

  return (
    <div className="routing-wrap section-paper" ref={ref} data-theme="paper">
      <div className="routing-sticky">
        <div className="routing-heads">
          <Head progress={progress} from={0.0} to={0.3} text="Polyweb picks one" />
          <Head progress={progress} from={0.3} to={0.58} text="If one fails" />
          <Head
            progress={progress}
            from={0.58}
            to={1}
            text="the next one answers"
          />
        </div>

        <div className="query-bar">
          <span className="query-caret" aria-hidden="true" />
          <motion.span className="query-text">{queryText}</motion.span>
        </div>

        <div className="track-area">
          <div className="track-line" aria-hidden="true" />
          <motion.div
            className="track-pulse"
            style={{ left: pulseX, opacity: pulseOpacity }}
            aria-hidden="true"
          />
          <div className="provider-row">
            {CARDS.map((_, i) => (
              <ProviderCard key={i} progress={progress} index={i} />
            ))}
          </div>
        </div>

        <div className="results-row">
          {RESULTS.map(([title, domain], i) => (
            <ResultCard
              key={title}
              title={title}
              domain={domain}
              reveal={results[i]}
            />
          ))}
        </div>

        <motion.p className="routing-final" style={{ opacity: finalCap }}>
          One request. No manual retry.
        </motion.p>
      </div>
    </div>
  )
}
