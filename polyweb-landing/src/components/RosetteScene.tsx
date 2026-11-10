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

const W = 1400
const H = 1000
const CX = 700
const CY = 500
const OCT_R = 72
const RING_DIST = 170
const RING_R = 50
const ORBIT = 380
const LOGO_ANGLES = [-90, -45, 0, 45, 90, 135, 180, 225]
const OCT_ANGLES = [22.5, 67.5, 112.5, 157.5, 202.5, 247.5, 292.5, 337.5]
const [ACTIVE_LOGO, NEXT_LOGO] = pickRandom([0, 1, 2, 3, 4, 5, 6, 7], 2) // the chosen provider, then its fallback
const NIGHT = "#070a12"
const FAINT = "#a3a9b8"

const rad = (deg: number) => (deg * Math.PI) / 180
const pt = (angle: number, r: number): [number, number] => [
  CX + r * Math.cos(rad(angle)),
  CY + r * Math.sin(rad(angle)),
]

// Flat-top octagon: vertices offset 22.5° from the provider angles.
const OCT_POINTS = OCT_ANGLES.map((a) => pt(a, OCT_R).join(",")).join(" ")

function FaintBeam({
  progress,
  index,
}: {
  progress: MotionValue<number>
  index: number
}) {
  const from = 0.18 + index * 0.03
  const length = useTransform(progress, [from, from + 0.1], [0, 1], {
    clamp: true,
  })
  const [x1, y1] = pt(LOGO_ANGLES[index], OCT_R - 4)
  const [x2, y2] = pt(LOGO_ANGLES[index], ORBIT - 46)
  return (
    <motion.line
      x1={x1}
      y1={y1}
      x2={x2}
      y2={y2}
      stroke={FAINT}
      strokeWidth={1.2}
      strokeOpacity={0.22}
      strokeLinecap="round"
      style={{ pathLength: length }}
    />
  )
}

function ActiveBeam({
  progress,
  index,
  from,
  to,
  dimAfter,
}: {
  progress: MotionValue<number>
  index: number
  from: number
  to: number
  dimAfter?: [number, number]
}) {
  const appear = useTransform(progress, [from, to], [0, 1], { clamp: true })
  const dim = useTransform(
    progress,
    dimAfter ?? [0, 0],
    dimAfter ? [1, 0.12] : [1, 1],
    { clamp: true }
  )
  const opacity = useTransform(
    [appear, dim] as MotionValue<number>[],
    (v) => (v[0] as number) * (v[1] as number)
  )
  const [x1, y1] = pt(LOGO_ANGLES[index], OCT_R - 4)
  const [x2, y2] = pt(LOGO_ANGLES[index], ORBIT - 46)
  return (
    <motion.line
      x1={x1}
      y1={y1}
      x2={x2}
      y2={y2}
      stroke="url(#rosette-grad)"
      strokeWidth={2.4}
      strokeLinecap="round"
      style={{ opacity }}
    />
  )
}

function DashedBeam({
  progress,
  index,
  from,
  to,
}: {
  progress: MotionValue<number>
  index: number
  from: number
  to: number
}) {
  const opacity = useTransform(progress, [from, to], [0, 0.35], {
    clamp: true,
  })
  const [x1, y1] = pt(LOGO_ANGLES[index], OCT_R - 4)
  const [x2, y2] = pt(LOGO_ANGLES[index], ORBIT - 46)
  return (
    <motion.line
      x1={x1}
      y1={y1}
      x2={x2}
      y2={y2}
      stroke={FAINT}
      strokeWidth={1.4}
      strokeLinecap="round"
      strokeDasharray="5 7"
      style={{ opacity }}
    />
  )
}

function OrbitLogo({
  progress,
  index,
  failed,
}: {
  progress: MotionValue<number>
  index: number
  failed: boolean
}) {
  const start = 0.2 + index * 0.03
  const appear = useTransform(progress, [start, start + 0.08], [0, 1], {
    clamp: true,
  })
  const dim = useTransform(progress, [0.74, 0.86], [1, failed ? 0.3 : 1], {
    clamp: true,
  })
  const opacity = useTransform(
    [appear, dim] as MotionValue<number>[],
    (v) => (v[0] as number) * (v[1] as number)
  )

  const [x, y] = pt(LOGO_ANGLES[index], ORBIT)
  return (
    <motion.div
      className="orbit-logo"
      style={{
        left: `${(x / W) * 100}%`,
        top: `${(y / H) * 100}%`,
        x: "-50%",
        y: "-50%",
        opacity,
      }}
    >
      <img src={PROVIDERS[index].src} alt={PROVIDERS[index].name} width={30} height={30} />
    </motion.div>
  )
}

function Caption({
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
    [from, from + 0.04, to - 0.04, to],
    [0, 1, 1, 0]
  )
  const y = useTransform(progress, [from, from + 0.04], [10, 0])
  return (
    <motion.p className="rosette-caption" style={{ opacity, y, x: "-50%" }}>
      {text}
    </motion.p>
  )
}

function DrawnRing({
  progress,
  index,
}: {
  progress: MotionValue<number>
  index: number
}) {
  const from = 0.03 + index * 0.015
  const length = useTransform(progress, [from, from + 0.09], [0, 1], {
    clamp: true,
  })
  const [x, y] = pt(LOGO_ANGLES[index], RING_DIST)
  return (
    <motion.circle
      cx={x}
      cy={y}
      r={RING_R}
      fill={NIGHT}
      stroke="url(#rosette-grad)"
      strokeWidth={5}
      style={{ pathLength: length }}
    />
  )
}

export function RosetteScene() {
  const ref = useRef<HTMLDivElement>(null)
  const reduced = useReducedMotion()
  const { scrollYProgress } = useScroll({
    target: ref,
    offset: ["start start", "end end"],
  })
  const done = useMotionValue(1)
  const progress = reduced ? done : scrollYProgress

  const queryLine = useTransform(progress, [0.01, 0.12], [0, 1], {
    clamp: true,
  })
  const octDraw = useTransform(progress, [0.02, 0.12], [0, 1], {
    clamp: true,
  })

  return (
    <div
      className="rosette-wrap section-night"
      ref={ref}
      id="features"
      data-theme="night"
    >
      <div className="rosette-sticky">
        <div className="rosette-stage" aria-hidden="true">
          <svg
            className="rosette-svg"
            viewBox={`0 0 ${W} ${H}`}
            fill="none"
            role="img"
            aria-label="A query entering the Polyweb rosette and fanning out to eight providers"
          >
            <defs>
              <linearGradient id="rosette-grad" x1="0" y1="1" x2="1" y2="0">
                <stop offset="0" stopColor="#b8035e" />
                <stop offset="1" stopColor="#fe8a0b" />
              </linearGradient>
            </defs>

            {/* the query enters the octagon */}
            <motion.line
              x1={64}
              y1={CY}
              x2={CX - OCT_R}
              y2={CY}
              stroke="url(#rosette-grad)"
              strokeWidth={2.5}
              strokeLinecap="round"
              style={{ pathLength: queryLine }}
            />

            {/* faint beams out to all eight providers (drawn beneath the rings) */}
            {LOGO_ANGLES.map((_, i) => (
              <FaintBeam key={`faint-${i}`} progress={progress} index={i} />
            ))}

            {/* the chosen provider's beam brightens; on failure it dims to a
                dashed line while the next provider's beam takes over */}
            <ActiveBeam
              progress={progress}
              index={ACTIVE_LOGO}
              from={0.42}
              to={0.55}
              dimAfter={[0.74, 0.86]}
            />
            <ActiveBeam
              progress={progress}
              index={NEXT_LOGO}
              from={0.8}
              to={0.93}
            />
            <DashedBeam progress={progress} index={ACTIVE_LOGO} from={0.74} to={0.86} />

            {/* the rosette mark: octagon + eight rings, one per provider,
                drawn on first */}
            <motion.polygon
              points={OCT_POINTS}
              fill={NIGHT}
              stroke="url(#rosette-grad)"
              strokeWidth={5}
              strokeLinejoin="round"
              style={{ pathLength: octDraw }}
            />
            {LOGO_ANGLES.map((_, i) => (
              <DrawnRing key={`ring-${i}`} progress={progress} index={i} />
            ))}
          </svg>

          {LOGO_ANGLES.map((_, i) => (
            <OrbitLogo
              key={i}
              progress={progress}
              index={i}
              failed={i === ACTIVE_LOGO}
            />
          ))}
        </div>

        <Caption
          progress={progress}
          from={0}
          to={0.3}
          text="Your query arrives once"
        />
        <Caption
          progress={progress}
          from={0.3}
          to={0.68}
          text="Polyweb picks a provider"
        />
        <Caption
          progress={progress}
          from={0.68}
          to={1}
          text="and falls back to the next if one fails"
        />
      </div>
    </div>
  )
}
