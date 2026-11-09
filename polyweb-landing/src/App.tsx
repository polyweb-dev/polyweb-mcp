import { useRef } from "react"
import {
  motion,
  useMotionValue,
  useReducedMotion,
  useScroll,
  useTransform,
  type MotionValue,
} from "motion/react"
import { Nav } from "./components/Nav"
import { Reveal, Revealed } from "./components/Reveal"
import { RosetteScene } from "./components/RosetteScene"
import { RoutingScene } from "./components/RoutingScene"

import logo from "./assets/polyweb.webp"
import heroPrism from "./assets/hero-prism.webp"
import projectsWide from "./assets/projects-wide.webp"
import selfhostWide from "./assets/selfhost-wide.webp"

import brave from "./assets/brave.webp"
import exa from "./assets/exa.webp"
import firecrawl from "./assets/firecrawl.webp"
import keenable from "./assets/keenable.webp"
import parallel from "./assets/parallel.webp"
import tavily from "./assets/tavily.webp"
import tinyfish from "./assets/tinyfish.webp"
import youcom from "./assets/youcom.webp"

const GITHUB = "https://github.com/polyweb-dev/polyweb"

const PROVIDERS: Array<[string, string]> = [
  ["Brave Search", brave],
  ["Exa", exa],
  ["Firecrawl", firecrawl],
  ["Tavily", tavily],
  ["Parallel", parallel],
  ["You.com", youcom],
  ["Keenable", keenable],
  ["Tinyfish", tinyfish],
]

function Hero() {
  return (
    <div className="section-night" id="top" data-theme="night">
      <section className="hero" aria-label="Polyweb introduction">
        <img
          className="hero-img"
          src={heroPrism}
          alt="A beam of light splitting through a glass prism into eight beams"
          width={3136}
          height={1344}
          fetchPriority="high"
        />
        <div className="hero-fade-x" aria-hidden="true" />
        <div className="hero-fade-b" aria-hidden="true" />
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
        {PROVIDERS.map(([name, src]) => (
          <img key={name} src={src} alt={name} />
        ))}
      </div>
    </div>
  )
}

/* ---------- credits gauges ---------- */

const GAUGES: Array<{
  name: string
  src: string
  value: number
  of: number
  fill: number
  label: string
}> = [
  { name: "Brave Search", src: brave, value: 642, of: 1000, fill: 0.64, label: "credits left this month" },
  { name: "Tavily", src: tavily, value: 818, of: 1000, fill: 0.82, label: "credits left this month" },
  { name: "Exa", src: exa, value: 231, of: 500, fill: 0.46, label: "credits left this month" },
  { name: "Keenable", src: keenable, value: 412, of: 1000, fill: 0.41, label: "requests left this hour · keyless" },
]

const GAUGE_R = 118
const GAUGE_C = 2 * Math.PI * GAUGE_R

function Gauge({ g, progress }: { g: (typeof GAUGES)[number]; progress: MotionValue<number> }) {
  const dash = useTransform(progress, [0, 1], [0, g.fill * GAUGE_C], { clamp: true })
  const dasharray = useTransform(dash, (d) => `${d} ${GAUGE_C}`)
  const num = useTransform(progress, (v) => String(Math.round(v * g.value)))
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
      <img className="gauge-logo" src={g.src} alt={g.name} />
      <motion.span className="gauge-num">{num}</motion.span>
      <span className="gauge-label">{g.label}</span>
    </div>
  )
}

function Credits() {
  const ref = useRef<HTMLDivElement>(null)
  const reduced = useReducedMotion()
  const { scrollYProgress } = useScroll({ target: ref, offset: ["start 0.85", "start 0.35"] })
  const done = useMotionValue(1)
  const progress = reduced ? done : scrollYProgress
  return (
    <section className="section section-night" data-theme="night" aria-label="Credits and limits">
      <div className="container" ref={ref} style={{ textAlign: "center" }}>
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
            <Gauge key={g.name} g={g} progress={progress} />
          ))}
        </div>
      </div>
    </section>
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
  ["TB", "tom.baier@acme.co", "Member"],
  ["LN", "lena.nakamura@acme.co", "Admin"],
  ["RO", "ravi.okafor@acme.co", "Member"],
]
const KEY_TEXT = "fs_live_7Hk2xQ9mR4vN"
const KEY_PREFIX = "fs_live_"

function KeyField() {
  const ref = useRef<HTMLDivElement>(null)
  const reduced = useReducedMotion()
  const { scrollYProgress } = useScroll({
    target: ref,
    offset: ["start 0.85", "end 0.35"],
  })
  const done = useMotionValue(1)
  const progress = reduced ? done : scrollYProgress
  const typedN = useTransform(progress, [0, 0.35], [0, KEY_TEXT.length], {
    clamp: true,
  })
  const maskN = useTransform(
    progress,
    [0.5, 0.85],
    [0, KEY_TEXT.length - KEY_PREFIX.length],
    { clamp: true }
  )
  const copyOn = useTransform(progress, [0.88, 0.95], [0, 1], { clamp: true })
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
    <div ref={ref} style={{ marginTop: "auto", marginBottom: "auto" }}>
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

const EVENTS = [
  ["search", brave, "Brave Search · answered"],
  ["fetch", firecrawl, "Firecrawl · answered"],
  ["search", exa, "Exa · answered"],
  ["fetch", tavily, "Tavily · answered"],
]

function Bento() {
  return (
    <section className="section-paper" data-theme="paper" aria-label="Projects">
      <div className="bento">
        <Revealed>
          <div className="bento-tile">
            <h3 className="bento-title">Members and roles</h3>
            <div>
              {MEMBERS.map(([ini, mail, role], i) => (
                <div className="member-row" key={mail} style={{ transitionDelay: `${i * 90}ms` }}>
                  <span className="member-avatar">{ini}</span>
                  <span className="member-mail">{mail}</span>
                  <span className="role-pill">{role}</span>
                </div>
              ))}
            </div>
          </div>
        </Revealed>
        <Revealed>
          <div className="bento-tile bento-tile-center">
            <h3 className="bento-title">Keys shown once</h3>
            <KeyField />
            <p className="key-note">Shown once. Only a verifier is stored.</p>
          </div>
        </Revealed>
        <Revealed>
          <div className="bento-tile">
            <h3 className="bento-title">Activity you can trust</h3>
            <div className="timeline">
              {EVENTS.map(([tag, src, meta], i) => (
                <div className="timeline-row" key={String(meta)} style={{ transitionDelay: `${i * 90}ms` }}>
                  <span className="timeline-dot" aria-hidden="true" />
                  <span className="timeline-tag">{tag}</span>
                  <img src={src as string} alt="" />
                  <span className="timeline-meta">{meta}</span>
                </div>
              ))}
            </div>
          </div>
        </Revealed>
      </div>
    </section>
  )
}

/* ---------- shared capacity ---------- */

function Capacity() {
  return (
    <section className="section section-paper" data-theme="paper" aria-label="Shared capacity">
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
        <Revealed className="pool-big">
          <div className="pool-big-labels">
            <span className="pool-big-label" style={{ width: "40%" }}>
              Research <span className="pool-fig">strict cap 400</span>
            </span>
            <span className="pool-big-label" style={{ width: "35%" }}>
              Support <span className="pool-fig">strict cap 350</span>
            </span>
            <span className="pool-big-label" style={{ width: "25%" }}>
              Growth <span className="pool-fig">150 + loan</span>
            </span>
          </div>
          <div className="pool-total">1,000 requests per minute</div>
          <div className="pool-big-bar">
            <div className="pool-big-seg" style={{ width: "40%" }} />
            <div className="pool-big-seg" style={{ width: "35%" }} />
            <div className="pool-big-seg" style={{ width: "15%" }} />
            <div className="pool-big-unused" style={{ width: "10%" }}>
              <div className="pool-big-loan" />
            </div>
          </div>
          <p className="pool-loan-note">
            Loan · borrows idle capacity, up to a max rate
          </p>
        </Revealed>
      </div>
    </section>
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
  const opacity = useTransform(progress, [0.08 + index * 0.09, 0.15 + index * 0.09], [0, 1], { clamp: true })
  return (
    <motion.div className={`agents-line-${kind}`} style={{ opacity }}>
      {text}
    </motion.div>
  )
}

function Agents() {
  const ref = useRef<HTMLDivElement>(null)
  const reduced = useReducedMotion()
  const { scrollYProgress } = useScroll({ target: ref, offset: ["start 0.8", "start 0.2"] })
  const done = useMotionValue(1)
  const progress = reduced ? done : scrollYProgress
  return (
    <section className="section section-night" id="agents" data-theme="night" aria-label="For agents">
      <div className="container" ref={ref}>
        <Reveal>
          <h2 className="headline">Built for agents</h2>
        </Reveal>
        <Reveal delay={0.08}>
          <p className="subhead">
            The MCP server runs over streamable HTTP and accepts project API
            keys. An agent searches and fetches inside its own project scopes
          </p>
        </Reveal>
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
        <Reveal delay={0.2}>
          <pre className="code-block agents-curl">{`curl http://<host>:8001/search \\
  -H "Authorization: Bearer fs_live_..." \\
  -H "Content-Type: application/json" \\
  -d '{"query": "latest climate research", "limit": 10}'`}</pre>
        </Reveal>
      </div>
    </section>
  )
}

/* ---------- self-host ---------- */

function SelfHost() {
  const ref = useRef<HTMLElement>(null)
  const reduced = useReducedMotion()
  const { scrollYProgress } = useScroll({ target: ref, offset: ["start end", "end start"] })
  const done = useMotionValue(0)
  const progress = reduced ? done : scrollYProgress
  const scale = useTransform(progress, [0, 1], [1.15, 1])
  return (
    <div className="section-night" id="self-host" data-theme="night" ref={ref as never}>
      <section className="selfhost-wrap" aria-label="Self-hosted">
        <motion.img
          className="selfhost-img"
          src={selfhostWide}
          alt="A small graphite server box lit by a desk lamp at night"
          style={{ scale }}
        />
        <div className="selfhost-fade" aria-hidden="true" />
        <div className="container">
          <div className="selfhost-content">
            <Reveal>
              <h2 className="cta-head">Runs on your hardware</h2>
            </Reveal>
          </div>
        </div>
      </section>
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

function CtaRosette({ progress }: { progress: MotionValue<number> }) {
  const rotate = useTransform(progress, [0, 1], [0, 30])
  const cx = 250, cy = 250
  const pt = (a: number, r: number): [number, number] => [
    cx + r * Math.cos((a * Math.PI) / 180),
    cy + r * Math.sin((a * Math.PI) / 180),
  ]
  const hex = [0, 60, 120, 180, 240, 300].map((a) => pt(a, 72).join(",")).join(" ")
  return (
    <motion.svg
      className="cta-rosette"
      viewBox="0 0 500 500"
      fill="none"
      style={{ rotate }}
      aria-hidden="true"
    >
      <defs>
        <linearGradient id="cta-grad" x1="0" y1="1" x2="1" y2="0">
          <stop offset="0" stopColor="#0047ff" />
          <stop offset="1" stopColor="#19d3f5" />
        </linearGradient>
      </defs>
      <polygon points={hex} stroke="url(#cta-grad)" strokeWidth="7" strokeLinejoin="round" />
      {[0, 60, 120, 180, 240, 300].map((a) => {
        const [x, y] = pt(a, 158)
        return <circle key={a} cx={x} cy={y} r={54} stroke="url(#cta-grad)" strokeWidth="7" />
      })}
    </motion.svg>
  )
}

function FinalCta() {
  const ref = useRef<HTMLDivElement>(null)
  const reduced = useReducedMotion()
  const { scrollYProgress } = useScroll({ target: ref, offset: ["start end", "end start"] })
  const done = useMotionValue(0.5)
  const progress = reduced ? done : scrollYProgress
  return (
    <div className="section-night" data-theme="night" ref={ref}>
      <section className="section" aria-label="Get started">
        <div className="container cta-inner">
          <CtaRosette progress={progress} />
          <Reveal>
            <h2 className="cta-head">Point one API at every provider</h2>
          </Reveal>
          <Reveal delay={0.12}>
            <div className="cta-buttons">
              <a className="button button-primary" href={GITHUB} target="_blank" rel="noreferrer">
                View on GitHub
              </a>
              <a className="button button-secondary-dark" href="#self-host">
                Get started
              </a>
            </div>
          </Reveal>
        </div>
      </section>
      <footer className="footer">
        <div className="footer-inner">
          <img src={logo} alt="" width={20} height={20} />
          <span>© Polyweb</span>
          <a href={GITHUB} target="_blank" rel="noreferrer" style={{ marginLeft: "auto" }}>
            github.com/polyweb-dev/polyweb
          </a>
        </div>
      </footer>
    </div>
  )
}

export function App() {
  return (
    <>
      <Nav />
      <main>
        <Hero />
        <RosetteScene />
        <RoutingScene />
        <Credits />
        <ProjectsReveal />
        <Bento />
        <Capacity />
        <Agents />
        <SelfHost />
        <FinalCta />
      </main>
    </>
  )
}
