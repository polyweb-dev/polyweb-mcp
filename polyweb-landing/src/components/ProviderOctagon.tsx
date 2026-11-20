import { motion, useReducedMotion } from "motion/react"

import { PROVIDERS } from "../providers"
import polyweb from "../assets/polyweb.webp"

const W = 560
const CX = 280
const CY = 280
const OCT_R = 58
const RING_DIST = 168
const RING_R = 48
const NIGHT = "#070a12"

const LOGO_ANGLES = [-90, -45, 0, 45, 90, 135, 180, 225]
const OCT_ANGLES = [22.5, 67.5, 112.5, 157.5, 202.5, 247.5, 292.5, 337.5]

const rad = (deg: number) => (deg * Math.PI) / 180
const pt = (angle: number, r: number): [number, number] => [
  CX + r * Math.cos(rad(angle)),
  CY + r * Math.sin(rad(angle)),
]

const OCT_POINTS = OCT_ANGLES.map((a) => pt(a, OCT_R).join(",")).join(" ")

/** Static octagon mark for the Providers section: an octagon ringed by
 * one ring per provider, drawn once when it scrolls into view. */
export function ProviderOctagon() {
  const reduced = useReducedMotion()
  const lineInitial = reduced ? false : { pathLength: 0 }
  const fadeInitial = reduced ? false : { opacity: 0 }
  return (
    <div
      className="prov-oct"
      role="img"
      aria-label="The Polyweb octagon ringed by the eight providers"
    >
      <svg className="prov-oct-svg" viewBox={`0 0 ${W} ${W}`} fill="none">
        <defs>
          <linearGradient id="prov-oct-grad" x1="0" y1="1" x2="1" y2="0">
            <stop offset="0" stopColor="#b8035e" />
            <stop offset="1" stopColor="#fe8a0b" />
          </linearGradient>
        </defs>
        <motion.polygon
          points={OCT_POINTS}
          fill={NIGHT}
          stroke="url(#prov-oct-grad)"
          strokeWidth={4}
          strokeLinejoin="round"
          initial={lineInitial}
          whileInView={{ pathLength: 1 }}
          viewport={{ once: true, margin: "-15% 0px" }}
          transition={{ duration: 0.8, ease: "easeOut" }}
        />
        {LOGO_ANGLES.map((a, i) => {
          const [x1, y1] = pt(a, OCT_R + 4)
          const [x2, y2] = pt(a, RING_DIST - RING_R - 6)
          const [rx, ry] = pt(a, RING_DIST)
          return (
            <g key={a}>
              <motion.line
                x1={x1}
                y1={y1}
                x2={x2}
                y2={y2}
                stroke="#a3a9b8"
                strokeWidth={1.2}
                strokeLinecap="round"
                strokeOpacity={0.25}
                initial={lineInitial}
                whileInView={{ pathLength: 1 }}
                viewport={{ once: true, margin: "-15% 0px" }}
                transition={{ duration: 0.5, delay: 0.4 + i * 0.05 }}
              />
              <motion.circle
                cx={rx}
                cy={ry}
                r={RING_R}
                fill={NIGHT}
                stroke="url(#prov-oct-grad)"
                strokeWidth={3.5}
                initial={lineInitial}
                whileInView={{ pathLength: 1 }}
                viewport={{ once: true, margin: "-15% 0px" }}
                transition={{ duration: 0.55, delay: 0.15 + i * 0.05 }}
              />
            </g>
          )
        })}
      </svg>
      <motion.div
        className="prov-oct-logo prov-oct-center"
        initial={fadeInitial}
        whileInView={{ opacity: 1 }}
        viewport={{ once: true, margin: "-15% 0px" }}
        transition={{ duration: 0.4, delay: 0.3 }}
      >
        <img src={polyweb} alt="Polyweb" />
      </motion.div>
      {LOGO_ANGLES.map((a, i) => {
        const [x, y] = pt(a, RING_DIST)
        return (
          <motion.div
            key={a}
            className="prov-oct-logo"
            style={{ left: `${(x / W) * 100}%`, top: `${(y / W) * 100}%` }}
            initial={fadeInitial}
            whileInView={{ opacity: 1 }}
            viewport={{ once: true, margin: "-15% 0px" }}
            transition={{ duration: 0.4, delay: 0.4 + i * 0.05 }}
          >
            <img src={PROVIDERS[i].src} alt={PROVIDERS[i].name} />
          </motion.div>
        )
      })}
    </div>
  )
}
