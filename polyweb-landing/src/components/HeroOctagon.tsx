import { motion, useReducedMotion } from "motion/react"

import { PROVIDERS } from "../providers"
import polyweb from "../assets/polyweb.webp"

const W = 520
const CX = 260
const CY = 260
const VERTEX_R = 208
const PLATE_R = 34
const CENTER_PLATE_R = 52

// Flat-top octagon vertices: offset 22.5° from the cardinal angles.
const VERTEX_ANGLES = [22.5, 67.5, 112.5, 157.5, 202.5, 247.5, 292.5, 337.5]

const rad = (deg: number) => (deg * Math.PI) / 180
const pt = (angle: number, r: number): [number, number] => [
  CX + r * Math.cos(rad(angle)),
  CY + r * Math.sin(rad(angle)),
]

const OCT_POINTS = VERTEX_ANGLES.map((a) => pt(a, VERTEX_R).join(",")).join(" ")

const lerp = (a: number, b: number, t: number) => a + (b - a) * t
const lerpHex = (from: string, to: string, t: number) => {
  const f = parseInt(from.slice(1), 16)
  const tt = parseInt(to.slice(1), 16)
  const c =
    (Math.round(lerp((f >> 16) & 255, (tt >> 16) & 255, t)) << 16) |
    (Math.round(lerp((f >> 8) & 255, (tt >> 8) & 255, t)) << 8) |
    Math.round(lerp(f & 255, tt & 255, t))
  return `#${c.toString(16).padStart(6, "0")}`
}

/** Hero object: an octagon of provider plates around a central Polyweb
 * plate, with thin magenta→orange spokes that draw in once on load. */
export function HeroOctagon() {
  const reduced = useReducedMotion()
  const lineInitial = reduced ? false : { pathLength: 0 }
  return (
    <div className="hero-oct" aria-hidden="true">
      <svg className="hero-oct-svg" viewBox={`0 0 ${W} ${W}`} fill="none">
        <motion.polygon
          points={OCT_POINTS}
          stroke="rgba(238, 240, 245, 0.18)"
          strokeWidth={1.5}
          strokeLinejoin="round"
          initial={lineInitial}
          animate={{ pathLength: 1 }}
          transition={{ duration: 0.9, ease: "easeOut" }}
        />
        {VERTEX_ANGLES.map((a, i) => {
          const [x1, y1] = pt(a, CENTER_PLATE_R + 6)
          const [x2, y2] = pt(a, VERTEX_R - PLATE_R - 8)
          return (
            <motion.line
              key={a}
              x1={x1}
              y1={y1}
              x2={x2}
              y2={y2}
              stroke={lerpHex("#b8035e", "#fe8a0b", i / (VERTEX_ANGLES.length - 1))}
              strokeWidth={1.25}
              strokeLinecap="round"
              strokeOpacity={0.5}
              initial={lineInitial}
              animate={{ pathLength: 1 }}
              transition={{
                duration: 0.7,
                delay: 0.6 + i * 0.05,
                ease: "easeOut",
              }}
            />
          )
        })}
      </svg>
      {VERTEX_ANGLES.map((a, i) => {
        const [x, y] = pt(a, VERTEX_R)
        return (
          <motion.div
            key={a}
            className="hero-oct-plate"
            style={{ left: `${(x / W) * 100}%`, top: `${(y / W) * 100}%` }}
            initial={reduced ? false : { opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ duration: 0.5, delay: 0.5 + i * 0.05 }}
          >
            <img src={PROVIDERS[i].src} alt={PROVIDERS[i].name} />
          </motion.div>
        )
      })}
      <motion.div
        className="hero-oct-plate hero-oct-center"
        initial={reduced ? false : { opacity: 0, scale: 0.9 }}
        animate={{ opacity: 1, scale: 1 }}
        transition={{ duration: 0.6, delay: 0.2 }}
      >
        <img src={polyweb} alt="Polyweb" />
      </motion.div>
      <div className="hero-oct-floor" />
    </div>
  )
}
