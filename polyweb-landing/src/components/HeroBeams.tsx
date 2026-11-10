import { motion, useReducedMotion } from "motion/react"

const VIEW_W = 1600
const VIEW_H = 700
const ENTRY_Y = VIEW_H * 0.55
const BEAM_START_X = VIEW_W * 0.52
const SPLIT_X = VIEW_W * 0.66
const FAN_COUNT = 8
const FAN_SPREAD_DEG = 14
const FAN_END_X = VIEW_W + 60
const EASE = [0.22, 1, 0.36, 1] as const

function lerpHex(a: string, b: string, t: number): string {
  const channel = (hex: string, i: number) =>
    parseInt(hex.slice(1 + i * 2, 3 + i * 2), 16)
  const mix = [0, 1, 2].map((i) =>
    Math.round(channel(a, i) + (channel(b, i) - channel(a, i)) * t)
  )
  return `#${mix.map((v) => v.toString(16).padStart(2, "0")).join("")}`
}

const FAN = Array.from({ length: FAN_COUNT }, (_, i) => {
  const t = i / (FAN_COUNT - 1)
  const angle =
    (-FAN_SPREAD_DEG + t * 2 * FAN_SPREAD_DEG) * (Math.PI / 180)
  const endY = ENTRY_Y + (FAN_END_X - SPLIT_X) * Math.tan(angle)
  return {
    d: `M ${SPLIT_X} ${ENTRY_Y} L ${FAN_END_X} ${endY.toFixed(1)}`,
    stroke: lerpHex("#b8035e", "#fe8a0b", t),
  }
})

export function HeroBeams() {
  const reduced = useReducedMotion()
  const initial = reduced ? (false as const) : { pathLength: 0 }
  return (
    <svg
      className="hero-img"
      viewBox={`0 0 ${VIEW_W} ${VIEW_H}`}
      preserveAspectRatio="xMidYMid slice"
      aria-hidden="true"
      fill="none"
    >
      <defs>
        <linearGradient
          id="hero-beam-in"
          gradientUnits="userSpaceOnUse"
          x1={BEAM_START_X}
          y1={ENTRY_Y}
          x2={SPLIT_X}
          y2={ENTRY_Y}
        >
          <stop offset="0" stopColor="#eef0f5" stopOpacity={0} />
          <stop offset="1" stopColor="#eef0f5" stopOpacity={0.35} />
        </linearGradient>
      </defs>
      <motion.path
        d={`M ${BEAM_START_X} ${ENTRY_Y} L ${SPLIT_X} ${ENTRY_Y}`}
        stroke="url(#hero-beam-in)"
        strokeWidth={1.25}
        initial={initial}
        animate={{ pathLength: 1 }}
        transition={{ duration: 0.9, ease: EASE }}
      />
      <motion.circle
        cx={SPLIT_X}
        cy={ENTRY_Y}
        r={2}
        fill="rgba(238, 240, 245, 0.5)"
        initial={reduced ? false : { opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ duration: 0.3, delay: 0.85 }}
      />
      {FAN.map((beam, i) => (
        <motion.path
          key={beam.d}
          d={beam.d}
          stroke={beam.stroke}
          strokeOpacity={0.45}
          strokeWidth={1}
          initial={initial}
          animate={{ pathLength: 1 }}
          transition={{ duration: 0.8, delay: 0.95 + i * 0.04, ease: EASE }}
        />
      ))}
    </svg>
  )
}
