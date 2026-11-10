import { useEffect, useRef, useState, type ComponentType, type ReactNode } from "react"
import {
  motion,
  useMotionValue,
  useReducedMotion,
  useScroll,
  useTransform,
  type MotionValue,
} from "motion/react"
import { SiteFooter } from "./components/Footer"
import { HeroBeams } from "./components/HeroBeams"
import { Nav } from "./components/Nav"
import { Reveal } from "./components/Reveal"
import { RosetteScene } from "./components/RosetteScene"
import { RoutingScene } from "./components/RoutingScene"
import { AboutPage } from "./pages/About"
import { FetchApiPage } from "./pages/FetchApi"
import { McpPage } from "./pages/Mcp"
import { NotFoundPage } from "./pages/NotFound"
import { ProjectsPage } from "./pages/Projects"
import { ProvidersPage } from "./pages/Providers"
import { SearchApiPage } from "./pages/SearchApi"
import { SecurityPage } from "./pages/Security"
import { SelfHostingPage } from "./pages/SelfHosting"
import { GITHUB } from "./links"
import { useMobile } from "./useMobile"

import projectsWide from "./assets/projects-wide.webp"
import { PROVIDERS, pickRandom } from "./providers"

function Hero() {
  return (
    <div className="section-night" id="top" data-theme="night">
      <section className="hero" aria-label="Polyweb introduction">
        <HeroBeams />
        <div className="container">
          <div className="hero-content">
            <Reveal>
              <h1 className="hero-headline">
                <span className="hero-line">One search API.</span>
                <span className="hero-line">Every provider.</span>
              </h1>
            </Reveal>
            <Reveal delay={0.08}>
              <p className="hero-sub">
                Polyweb routes search and fetch across eight providers,
                behind one REST API and an MCP server you host yourself.
              </p>
            </Reveal>
            <Reveal delay={0.16}>
              <div className="hero-actions">
                <a className="button button-primary" href="#self-host">
                  Get started
                </a>
                <a
                  className="button button-secondary-dark"
                  href={GITHUB}
                  target="_blank"
                  rel="noreferrer"
                >
                  View on GitHub
                </a>
              </div>
            </Reveal>
          </div>
        </div>
      </section>
      <div
        className="provider-strip"
        aria-label="Supported providers"
        data-theme="night"
      >
        {PROVIDERS.map((p) => (
          <img key={p.name} src={p.src} alt={p.name} />
        ))}
      </div>
    </div>
  )
}

/* ---------- credits gauges ---------- */

const GAUGE_PICKS = pickRandom(PROVIDERS, 4)
const GAUGES = [
  { value: 642, fill: 0.64, drain: 0.06 },
  { value: 818, fill: 0.82, drain: 0.09 },
  { value: 231, fill: 0.46, drain: 0.07 },
  { value: 412, fill: 0.41, drain: 0.10 },
].map((g, i) => ({ ...g, provider: GAUGE_PICKS[i] }))

const GAUGE_R = 118
const GAUGE_C = 2 * Math.PI * GAUGE_R

function Gauge({ g, progress }: { g: (typeof GAUGES)[number]; progress: MotionValue<number> }) {
  const fillT = useTransform(progress, [0, 0.4], [0, 1], { clamp: true })
  const drainT = useTransform(progress, [0.5, 0.95], [0, g.drain], { clamp: true })
  const level = useTransform([fillT, drainT] as MotionValue<number>[], (v) => {
    return (v[0] as number) * (1 - (v[1] as number))
  })
  const dash = useTransform(level, (l) => l * g.fill * GAUGE_C)
  const dasharray = useTransform(dash, (d) => `${d} ${GAUGE_C}`)
  const num = useTransform(level, (l) => String(Math.round(l * g.value)))
  return (
    <div className="gauge">
      <svg viewBox="0 0 264 264" aria-hidden="true">
        <circle className="gauge-track" cx="132" cy="132" r={GAUGE_R} fill="none" strokeWidth="14" />
        <motion.circle
          className="gauge-fill"
          cx="132"
          cy="132"
          r={GAUGE_R}
          fill="none"
          strokeWidth="14"
          style={{ strokeDasharray: dasharray }}
        />
      </svg>
      <img className="gauge-logo" src={g.provider.src} alt={g.provider.name} />
      <motion.span className="gauge-num">{num}</motion.span>
    </div>
  )
}

function Credits() {
  const ref = useRef<HTMLDivElement>(null)
  const reduced = useReducedMotion()
  const mobile = useMobile()
  const { scrollYProgress } = useScroll({ target: ref, offset: ["start start", "end end"] })
  const done = useMotionValue(1)
  const progress = reduced || mobile ? done : scrollYProgress
  return (
    <div className="pin-wrap credits-wrap section-night" ref={ref} data-theme="night" aria-label="Credits and limits">
      <div className="pin-sticky">
      <div className="container" style={{ textAlign: "center" }}>
        <Reveal>
          <h2 className="headline">
            <span className="hero-line">Know what</span>
            <span className="hero-line">every call costs</span>
          </h2>
        </Reveal>
        <Reveal delay={0.08}>
          <p className="subhead" style={{ margin: "24px auto 0" }}>
            Credits, rate limits and keyless tiers, tracked per provider and
            shown honestly
          </p>
        </Reveal>
        <div className="gauge-row">
          {GAUGES.map((g) => (
            <Gauge key={g.provider.name} g={g} progress={progress} />
          ))}
        </div>
      </div>
      </div>
    </div>
  )
}

/* ---------- projects: clip-path reveal + bento ---------- */

function ProjectsReveal() {
  const ref = useRef<HTMLDivElement>(null)
  const reduced = useReducedMotion()
  const { scrollYProgress } = useScroll({ target: ref, offset: ["start start", "end end"] })
  const done = useMotionValue(1)
  const progress = reduced ? done : scrollYProgress
  const clip = useTransform(
    progress,
    [0, 0.7],
    ["inset(18% 20% 18% 20% round 32px)", "inset(0% 0% 0% 0% round 0px)"]
  )
  const headOpacity = useTransform(progress, [0.15, 0.5], [0, 1], { clamp: true })
  const headScale = useTransform(progress, [0.15, 0.6], [0.92, 1])
  return (
    <div className="projects-wrap section-night" ref={ref} data-theme="night">
      <div className="projects-sticky">
        <motion.div className="projects-clip" style={{ clipPath: clip }}>
          <img
            src={projectsWide}
            alt="Three glass panes lit from within on a dark floor"
          />
        </motion.div>
        <motion.h2
          className="projects-head cta-head"
          style={{ opacity: headOpacity, scale: headScale }}
        >
          A workspace for every team
        </motion.h2>
      </div>
    </div>
  )
}

const MEMBERS = [
  ["MK", "mara.kovacs@acme.co", "Admin"],
  ["JW", "jon.wells@acme.co", "Member"],
  ["AS", "aisha.syed@acme.co", "Member"],
]
const KEY_TEXT = "fs_live_7Hk2xQ9m"
const KEY_PREFIX = "fs_live_"

function KeyField({ progress }: { progress: MotionValue<number> }) {
  const typedN = useTransform(progress, [0.2, 0.5], [0, KEY_TEXT.length], {
    clamp: true,
  })
  const maskN = useTransform(
    progress,
    [0.5, 0.7],
    [0, KEY_TEXT.length - KEY_PREFIX.length],
    { clamp: true }
  )
  const copyOn = useTransform(progress, [0.73, 0.78], [0, 1], { clamp: true })
  const copyOff = useTransform(copyOn, (v) => 1 - v)
  const chars = useTransform([typedN, maskN] as MotionValue<number>[], (v) => {
    const t = Math.round(v[0] as number)
    const m = Math.round(v[1] as number)
    return KEY_TEXT.split("")
      .map((c, i) =>
        i >= t ? "" : i < KEY_PREFIX.length || i - KEY_PREFIX.length >= m ? c : "•"
      )
      .join("")
  })
  return (
    <div style={{ marginTop: "auto", marginBottom: "auto" }}>
      <div className="key-field key-field-big">
        <motion.span className="key-live">{chars}</motion.span>
        <span className="key-copy">
          <motion.span style={{ opacity: copyOff, position: "absolute" }}>
            Copy
          </motion.span>
          <motion.span style={{ opacity: copyOn }}>Copied</motion.span>
        </span>
      </div>
    </div>
  )
}

const EVENT_FETCH = pickRandom(PROVIDERS.filter((p) => p.fetch), 1)[0]
const EVENT_SEARCH = pickRandom(
  PROVIDERS.filter((p) => p.search && p !== EVENT_FETCH),
  2
)
const EVENTS = [
  { tag: "search", provider: EVENT_SEARCH[0] },
  { tag: "fetch", provider: EVENT_FETCH },
  { tag: "search", provider: EVENT_SEARCH[1] },
]

function PinRow({
  progress,
  from,
  to,
  className,
  children,
}: {
  progress: MotionValue<number>
  from: number
  to: number
  className: string
  children: ReactNode
}) {
  const opacity = useTransform(progress, [from, to], [0, 1], { clamp: true })
  const y = useTransform(progress, [from, to], [10, 0])
  return (
    <motion.div className={className} style={{ opacity, y }}>
      {children}
    </motion.div>
  )
}

function Bento() {
  const ref = useRef<HTMLDivElement>(null)
  const reduced = useReducedMotion()
  const mobile = useMobile("(max-width: 860px)")
  const { scrollYProgress } = useScroll({ target: ref, offset: ["start start", "end end"] })
  const done = useMotionValue(1)
  const progress = reduced || mobile ? done : scrollYProgress
  return (
    <div className="pin-wrap bento-wrap section-paper" ref={ref} data-theme="paper" aria-label="Projects">
      <div className="pin-sticky">
        <div className="bento">
          <div className="bento-tile">
            <h3 className="bento-title">Members</h3>
            <div>
              {MEMBERS.map(([ini, mail, role], i) => (
                <PinRow key={mail} progress={progress} from={0.05 + i * 0.08} to={0.13 + i * 0.08} className="member-row">
                  <span className="member-avatar">{ini}</span>
                  <span className="member-mail">{mail}</span>
                  <span className="role-pill">{role}</span>
                </PinRow>
              ))}
            </div>
          </div>
          <div className="bento-tile bento-tile-center">
            <h3 className="bento-title">Keys shown once</h3>
            <KeyField progress={progress} />
          </div>
          <div className="bento-tile">
            <h3 className="bento-title">Activity</h3>
            <div className="timeline">
              {EVENTS.map((e, i) => (
                <PinRow key={e.provider.name + e.tag} progress={progress} from={0.45 + i * 0.11} to={0.56 + i * 0.11} className="timeline-row">
                  <span className="timeline-dot" aria-hidden="true" />
                  <span className="timeline-tag">{e.tag}</span>
                  <img src={e.provider.src} alt="" />
                  <span className="timeline-meta">{e.provider.name} · answered</span>
                </PinRow>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

/* ---------- shared capacity ---------- */

function Capacity() {
  const ref = useRef<HTMLDivElement>(null)
  const reduced = useReducedMotion()
  const mobile = useMobile()
  const { scrollYProgress } = useScroll({ target: ref, offset: ["start start", "end end"] })
  const done = useMotionValue(1)
  const progress = reduced || mobile ? done : scrollYProgress
  const s1 = useTransform(progress, [0.05, 0.3], [0, 1], { clamp: true })
  const s2 = useTransform(progress, [0.25, 0.5], [0, 1], { clamp: true })
  const s3 = useTransform(progress, [0.45, 0.65], [0, 1], { clamp: true })
  const s4 = useTransform(progress, [0.65, 0.85], [0, 1], { clamp: true })
  const meta = useTransform(progress, [0.82, 0.92], [0, 1], { clamp: true })
  return (
    <div className="pin-wrap capacity-wrap section-paper" ref={ref} data-theme="paper" aria-label="Shared capacity">
      <div className="pin-sticky">
      <div className="container">
        <Reveal>
          <h2 className="headline">Share one key fairly</h2>
        </Reveal>
        <Reveal delay={0.08}>
          <p className="subhead">
            Pool provider capacity and grant each project an allocation. Only
            system administrators change pools and allocations
          </p>
        </Reveal>
        <div className="pool-big">
          <div className="pool-big-labels">
            <motion.span className="pool-big-label" style={{ width: "40%", opacity: s1 }}>
              Research <span className="pool-fig">strict cap 400</span>
            </motion.span>
            <motion.span className="pool-big-label" style={{ width: "35%", opacity: s2 }}>
              Support <span className="pool-fig">strict cap 350</span>
            </motion.span>
            <motion.span className="pool-big-label" style={{ width: "25%", opacity: s3 }}>
              Growth <span className="pool-fig">150 + loan</span>
            </motion.span>
          </div>
          <motion.div className="pool-total" style={{ opacity: meta }}>1,000 requests per minute</motion.div>
          <div className="pool-big-bar">
            <motion.div className="pool-big-seg" style={{ width: "40%", scaleX: s1 }} />
            <motion.div className="pool-big-seg" style={{ width: "35%", scaleX: s2 }} />
            <motion.div className="pool-big-seg" style={{ width: "15%", scaleX: s3 }} />
            <div className="pool-big-unused" style={{ width: "10%" }}>
              <motion.div className="pool-big-loan" style={{ scaleX: s4 }} />
            </div>
          </div>
          <motion.p className="pool-loan-note" style={{ opacity: meta }}>
            Loan · borrows idle capacity, up to a max rate
          </motion.p>
        </div>
      </div>
      </div>
    </div>
  )
}

/* ---------- agents ---------- */

const AGENT_LINES = [
  ["dim", '{ "type": "streamable-http", "url": "http://<host>:8000/mcp" }'],
  ["call", '> search({ "query": "latest climate research" })'],
  ["out", "  1. Global temperature record broken in 2026 — nature.com"],
  ["out", "  2. How cities adapt to a warming coastline — reuters.com"],
  ["out", "  3. Ocean heat content hits a new high — noaa.gov"],
  ["call", '> fetch({ "url": "https://www.nature.com/articles/s41586-026-0142" })'],
  ["out", "  # Global temperature record broken in 2026"],
  ["out", "  Average surface temperature rose 0.4 C above the prior record."],
  ["out", "  Researchers attribute the rise to sustained ocean heat."],
]

function AgentLine({ index, kind, text, progress }: { index: number; kind: string; text: string; progress: MotionValue<number> }) {
  const opacity = useTransform(progress, [0.05 + index * 0.0775, 0.125 + index * 0.0775], [0, 1], { clamp: true })
  return (
    <motion.div className={`agents-line-${kind}`} style={{ opacity }}>
      {text}
    </motion.div>
  )
}

function Agents() {
  const ref = useRef<HTMLDivElement>(null)
  const reduced = useReducedMotion()
  const mobile = useMobile()
  const { scrollYProgress } = useScroll({ target: ref, offset: ["start start", "end end"] })
  const done = useMotionValue(1)
  const progress = reduced || mobile ? done : scrollYProgress
  const glowOpacity = useTransform(progress, [0, 0.3], [0, 1], { clamp: true })
  return (
    <div className="section-night" id="agents" data-theme="night" aria-label="For agents">
      <div className="pin-wrap agents-pin" ref={ref}>
      <div className="pin-sticky">
      <div className="container">
        <Reveal>
          <h2 className="headline">Built for agents</h2>
        </Reveal>
        <Reveal delay={0.08}>
          <p className="subhead">
            The MCP server runs over streamable HTTP and accepts project API
            keys. An agent searches and fetches inside its own project scopes
          </p>
        </Reveal>
        <div className="agents-stage">
          <motion.div
            className="agents-glow"
            style={{ opacity: glowOpacity }}
            aria-hidden="true"
          />
          <div className="agents-window">
            <div className="agents-titlebar" aria-hidden="true">
              <span className="agents-dot" />
              <span className="agents-dot" />
              <span className="agents-dot" />
            </div>
            <div className="agents-body">
              {AGENT_LINES.map(([kind, text], i) => (
                <AgentLine key={i} index={i} kind={kind} text={text} progress={progress} />
              ))}
            </div>
          </div>
        </div>
      </div>
      </div>
      </div>
    </div>
  )
}

/* ---------- self-host ---------- */

function SelfHost() {
  return (
    <div className="section-night" id="self-host" data-theme="night">
      <div className="selfhost-points">
        <Reveal>
          <div className="selfhost-point">
            <h3>One Compose file</h3>
            <p>
              API, MCP server and dashboard come up together
            </p>
            <p style={{ marginTop: 16 }}>
              <span className="code-chip">docker compose up --build -d</span>
            </p>
          </div>
        </Reveal>
        <Reveal delay={0.1}>
          <div className="selfhost-point">
            <h3>Keys encrypted at rest</h3>
            <p>Provider keys live in an encrypted on-disk vault</p>
          </div>
        </Reveal>
        <Reveal delay={0.2}>
          <div className="selfhost-point">
            <h3>Never returned by the API</h3>
            <p>No response ever contains secret material</p>
          </div>
        </Reveal>
      </div>
    </div>
  )
}

/* ---------- final CTA ---------- */

/* ---------- router ---------- */

const PAGES: Record<string, ComponentType> = {
  about: AboutPage,
  "search-api": SearchApiPage,
  "fetch-api": FetchApiPage,
  mcp: McpPage,
  providers: ProvidersPage,
  projects: ProjectsPage,
  "self-hosting": SelfHostingPage,
  security: SecurityPage,
}

function routeFromHash(hash: string): string | null {
  if (!hash.startsWith("#/")) return null
  const key = hash.slice(2).replace(/\/+$/, "")
  return key || null
}

function Home() {
  return (
    <>
      <Hero />
      <RosetteScene />
      <RoutingScene />
      <Credits />
      <ProjectsReveal />
      <Bento />
      <Capacity />
      <Agents />
      <SelfHost />
    </>
  )
}

export function App() {
  const [hash, setHash] = useState(() => window.location.hash)
  const lastHash = useRef(window.location.hash)
  const pendingAnchor = useRef<string | null>(null)

  useEffect(() => {
    const onHashChange = () => {
      const h = window.location.hash
      const wasPage = lastHash.current.startsWith("#/")
      lastHash.current = h
      if (routeFromHash(h) !== null) {
        pendingAnchor.current = null
      } else if (wasPage) {
        pendingAnchor.current = h.startsWith("#/") ? "" : h.slice(1)
      }
      setHash(h)
    }
    window.addEventListener("hashchange", onHashChange)
    return () => window.removeEventListener("hashchange", onHashChange)
  }, [])

  const route = routeFromHash(hash)

  useEffect(() => {
    if (route !== null) {
      window.scrollTo(0, 0)
      return
    }
    if (pendingAnchor.current !== null) {
      const id = pendingAnchor.current
      pendingAnchor.current = null
      if (id) {
        document.getElementById(id)?.scrollIntoView()
      } else {
        window.scrollTo(0, 0)
      }
    }
  }, [route])

  const Page = route !== null ? (PAGES[route] ?? NotFoundPage) : null

  return (
    <>
      <Nav page={route !== null} />
      <main>{Page ? <Page /> : <Home />}</main>
      <SiteFooter />
    </>
  )
}
