import { useEffect, useRef, useState, type ComponentType } from "react"
import {
  animate,
  motion,
  useInView,
  useMotionValue,
  useReducedMotion,
  useScroll,
  useTransform,
  type MotionValue,
} from "motion/react"
import { SiteFooter } from "./components/Footer"
import { HeroOctagon } from "./components/HeroOctagon"
import { Nav } from "./components/Nav"
import { ProviderOctagon } from "./components/ProviderOctagon"
import { Reveal } from "./components/Reveal"
import { RoutingPlayground } from "./components/RoutingPlayground"
import { AboutPage } from "./pages/About"
import { FetchApiPage } from "./pages/FetchApi"
import { McpPage } from "./pages/Mcp"
import { NotFoundPage } from "./pages/NotFound"
import { ProjectsPage } from "./pages/Projects"
import { ProvidersPage } from "./pages/Providers"
import { SearchApiPage } from "./pages/SearchApi"
import { SecurityPage } from "./pages/Security"
import { SelfHostingPage } from "./pages/SelfHosting"

import projectsWide from "./assets/projects-wide.webp"
import { PROVIDERS, pickRandom } from "./providers"

const EASE = [0.22, 1, 0.36, 1] as const
const SEARCHABLE = PROVIDERS.filter((p) => p.search)

/* ---------- random per-load provider picks ---------- */

const [REQ_PROVIDER] = pickRandom(SEARCHABLE, 1)
const STEP2_PROVIDERS = pickRandom(SEARCHABLE, 3)
const [WF_A, WF_B] = pickRandom(SEARCHABLE, 2)
const STEP4_PROVIDERS = pickRandom(PROVIDERS, 4)
const [ACT_FB_A, ACT_FB_B, ACT_QUOTA, ACT_HEALTH] = pickRandom(SEARCHABLE, 4)

/* ---------- hero ---------- */

function Hero() {
  return (
    <div className="section-night" id="top" data-theme="night">
      <section className="hero" aria-label="Polyweb introduction">
        <div className="container hero-inner">
          <Reveal>
            <p className="eyebrow">Self-hosted search gateway</p>
          </Reveal>
          <Reveal delay={0.06}>
            <h1 className="hero-headline">
              <span className="hero-line">One search API.</span>
              <span className="hero-line hero-line-accent">
                Every provider.
              </span>
            </h1>
          </Reveal>
          <Reveal delay={0.12}>
            <p className="hero-sub">
              Polyweb routes search and fetch across eight providers, behind
              one REST API and an MCP server you host yourself.
            </p>
          </Reveal>
          <Reveal delay={0.18}>
            <div className="hero-actions">
              <a className="button button-primary button-pill" href="#self-host">
                Get started
              </a>
              <a className="hero-link" href="#how">
                See how it works <span aria-hidden="true">›</span>
              </a>
            </div>
          </Reveal>
          <HeroOctagon />
        </div>
      </section>
    </div>
  )
}

/* ---------- manifesto ---------- */

const MANIFESTO =
  "Every search API has its own keys, limits, prices and ways to fail. Your agent shouldn't need to know any of them. Polyweb gives it one API, sends each call to a provider that's up and within budget, and moves on to the next one when it isn't."

function Word({
  progress,
  range,
  children,
}: {
  progress: MotionValue<number>
  range: [number, number]
  children: string
}) {
  const opacity = useTransform(progress, range, [0.18, 1], { clamp: true })
  return (
    <motion.span className="manifesto-word" style={{ opacity }}>
      {children}{" "}
    </motion.span>
  )
}

function Manifesto() {
  const ref = useRef<HTMLParagraphElement>(null)
  const reduced = useReducedMotion()
  const { scrollYProgress } = useScroll({
    target: ref,
    offset: ["start 0.85", "end 0.5"],
  })
  const words = MANIFESTO.split(" ")
  return (
    <div className="section-paper" data-theme="paper">
      <section className="section manifesto">
        <div className="container">
          <p ref={ref} className="manifesto-text">
            {reduced
              ? MANIFESTO
              : words.map((w, i) => (
                  <Word
                    key={i}
                    progress={scrollYProgress}
                    range={[i / words.length, (i + 1) / words.length]}
                  >
                    {w}
                  </Word>
                ))}
          </p>
        </div>
      </section>
    </div>
  )
}

/* ---------- how it works ---------- */

const STEPS = [
  {
    n: "01",
    title: "One request shape.",
    body: "POST /search or /fetch with the same JSON for every provider. Results come back in one format.",
  },
  {
    n: "02",
    title: "It picks a provider.",
    body: "Providers are tried in your project's order, cheapest first by default. Ones that are down, out of quota or switched off are skipped.",
  },
  {
    n: "03",
    title: "It falls back on its own.",
    body: "If a provider errors or hits a rate limit, the next one gets the call. The trace keeps every attempt.",
  },
  {
    n: "04",
    title: "It counts every call.",
    body: "Credits, quota and cost for each provider key, per project, on the Usage page.",
  },
]

const RESULT_ROWS = [
  ["Global temperature record broken in 2026", "nature.com"],
  ["How cities adapt to a warming coastline", "reuters.com"],
  ["Ocean heat content hits a new high", "noaa.gov"],
]

const STEP2_STATUS = [
  { label: "Skipped · out of quota", tone: "gray" },
  { label: "Skipped · down", tone: "gray" },
  { label: "Answered", tone: "green" },
]

const STEP4_VALUES = [
  { value: 642, fill: 0.64 },
  { value: 818, fill: 0.82 },
  { value: 231, fill: 0.46 },
  { value: 412, fill: 0.41 },
]

function CountUp({ value, on }: { value: number; on: boolean }) {
  const reduced = useReducedMotion()
  const mv = useMotionValue(reduced ? value : 0)
  const text = useTransform(mv, (v) => String(Math.round(v)))
  useEffect(() => {
    if (!on || reduced) {
      mv.set(value)
      return
    }
    const controls = animate(mv, value, { duration: 0.8, ease: "easeOut" })
    return () => controls.stop()
  }, [on, reduced, value, mv])
  return <motion.span className="how-count">{text}</motion.span>
}

function PanelBody({ step, on }: { step: number; on: boolean }) {
  if (step === 0) {
    return (
      <div className="panel-stack">
        <div className="panel-card">
          <p className="panel-card-head">
            <span className="panel-method">POST</span> /search
          </p>
          <pre className="panel-code">
            {`{ "query": "latest climate research",\n  "limit": 5 }`}
          </pre>
        </div>
        <div className="panel-card">
          <pre className="panel-code">
            {`{ "provider": "${REQ_PROVIDER.id}",\n  "results": [ … ] }`}
          </pre>
          <div className="panel-results">
            {RESULT_ROWS.map(([t, d]) => (
              <div className="panel-result" key={d}>
                <span className="panel-result-title">{t}</span>
                <span className="panel-result-domain">{d}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    )
  }
  if (step === 1) {
    return (
      <div className="panel-rows">
        {STEP2_PROVIDERS.map((p, i) => (
          <div className="panel-prow" key={p.id}>
            <img src={p.src} alt="" />
            <span className="panel-pname">{p.name}</span>
            <span className={`tag-pill tag-${STEP2_STATUS[i].tone}`}>
              {STEP2_STATUS[i].label}
            </span>
          </div>
        ))}
      </div>
    )
  }
  if (step === 2) {
    return (
      <div className="panel-rows">
        <div className="panel-wf">
          <div className="panel-wf-head">
            <span>{WF_A.name} request</span>
            <span className="panel-wf-code">429</span>
          </div>
          <div className="panel-wf-track">
            <div
              className="panel-wf-bar panel-wf-bar-fail"
              style={{ width: on ? "34%" : "0%" }}
            />
          </div>
        </div>
        <div className="panel-wf">
          <div className="panel-wf-head">
            <span>{WF_B.name} request</span>
            <span className="panel-wf-ms">812 ms</span>
          </div>
          <div className="panel-wf-track">
            <div
              className="panel-wf-bar"
              style={{ width: on ? "72%" : "0%" }}
            />
          </div>
        </div>
        <p className="panel-wf-note">2 attempts · second answered</p>
      </div>
    )
  }
  return (
    <div className="panel-rows">
      {STEP4_PROVIDERS.map((p, i) => (
        <div className="panel-meter" key={p.id}>
          <div className="panel-meter-head">
            <img src={p.src} alt="" />
            <span className="panel-pname">{p.name}</span>
            <CountUp value={STEP4_VALUES[i].value} on={on} />
          </div>
          <div className="panel-wf-track">
            <div
              className="panel-wf-bar"
              style={{ width: on ? `${STEP4_VALUES[i].fill * 100}%` : "0%" }}
            />
          </div>
        </div>
      ))}
    </div>
  )
}

function PanelFrame({ children }: { children: React.ReactNode }) {
  return (
    <div className="how-panel">
      <div className="how-panel-bar" aria-hidden="true">
        <span className="agents-dot" />
        <span className="agents-dot" />
        <span className="agents-dot" />
        <span className="how-panel-title">Polyweb</span>
      </div>
      <div className="how-panel-body">{children}</div>
    </div>
  )
}

function HowStep({
  index,
  onActive,
}: {
  index: number
  onActive: (i: number) => void
}) {
  const ref = useRef<HTMLDivElement>(null)
  const inView = useInView(ref, { amount: 0.6 })
  useEffect(() => {
    if (inView) onActive(index)
  }, [inView, index, onActive])
  const s = STEPS[index]
  return (
    <div className="how-step" ref={ref}>
      <div className="how-step-text">
        <span className="how-num">{s.n}</span>
        <h3>{s.title}</h3>
        <p>{s.body}</p>
      </div>
      <div className="how-step-panel">
        <PanelFrame>
          <PanelBody step={index} on={inView} />
        </PanelFrame>
      </div>
    </div>
  )
}

function HowItWorks() {
  const [active, setActive] = useState(0)
  return (
    <div className="section-paper" id="how" data-theme="paper">
      <section className="section how">
        <div className="container">
          <div className="how-head">
            <Reveal>
              <p className="eyebrow">How it works</p>
            </Reveal>
            <Reveal delay={0.06}>
              <h2 className="headline">
                <span className="hero-line">You send one request.</span>
                <span className="hero-line">Polyweb does the rest.</span>
              </h2>
            </Reveal>
            <Reveal delay={0.12}>
              <p className="subhead subhead-center">
                No SDK per provider. One request shape, one response shape,
                and a trace for every call.
              </p>
            </Reveal>
          </div>
          <div className="how-grid">
            <div className="how-steps">
              {STEPS.map((_, i) => (
                <HowStep key={i} index={i} onActive={setActive} />
              ))}
            </div>
            <div className="how-rail">
              <div className="how-sticky">
                <PanelFrame>
                  {STEPS.map((_, i) => (
                    <div
                      key={i}
                      className={`how-panel-step${i === active ? " on" : ""}`}
                    >
                      <PanelBody step={i} on={i === active} />
                    </div>
                  ))}
                </PanelFrame>
              </div>
            </div>
          </div>
          <div className="play-wrap">
            <Reveal>
              <h3 className="play-title">Try it. Break a provider.</h3>
            </Reveal>
            <Reveal delay={0.06}>
              <RoutingPlayground />
            </Reveal>
          </div>
        </div>
      </section>
    </div>
  )
}

/* ---------- providers ---------- */

const PROVIDER_ROWS: [id: string, cap: string][] = [
  ["brave", "Search"],
  ["exa", "Search · Fetch"],
  ["firecrawl", "Search · Fetch"],
  ["keenable", "Search · Fetch · works without a key"],
  ["parallel", "Search · Fetch"],
  ["tavily", "Search · Fetch · works without a key"],
  ["tinyfish", "Search · Fetch"],
  ["you", "Search · Fetch"],
]

function ProvidersSection() {
  const [active, setActive] = useState<string | null>(null)
  return (
    <div className="section-night" id="providers" data-theme="night">
      <section className="section providers">
        <div className="container">
          <div className="how-head">
            <Reveal>
              <p className="eyebrow">Providers</p>
            </Reveal>
            <Reveal delay={0.06}>
              <h2 className="headline">
                <span className="hero-line">Eight providers.</span>
                <span className="hero-line">One contract.</span>
              </h2>
            </Reveal>
          </div>
          <div className="prov-grid">
            <ProviderOctagon active={active} onActive={setActive} />
            <ol className="prov-list" onMouseLeave={() => setActive(null)}>
              {PROVIDER_ROWS.map(([id, cap], i) => {
                const p = PROVIDERS.find((x) => x.id === id)!
                return (
                  <Reveal key={id} delay={0.05 * i}>
                    <li
                      className={`prov-item${active === id ? " on" : ""}`}
                      tabIndex={0}
                      onMouseEnter={() => setActive(id)}
                      onFocus={() => setActive(id)}
                      onBlur={() => setActive(null)}
                    >
                      <span className="prov-num">
                        {String(i + 1).padStart(2, "0")}
                      </span>
                      <span className="prov-name">{p.name}</span>
                      <span className="prov-cap">{cap}</span>
                    </li>
                  </Reveal>
                )
              })}
            </ol>
          </div>
        </div>
      </section>
    </div>
  )
}

/* ---------- activity examples ---------- */

const ACT_CARDS: {
  label: string
  tag: string
  tone: string
  stmt?: string
  code?: string
  note: string
}[] = [
  {
    label: "Fallback",
    tag: "Fell back",
    tone: "amber",
    stmt: `${ACT_FB_A.name} hit a rate limit. ${ACT_FB_B.name} answered.`,
    note: "Your agent still gets results. The trace keeps both attempts.",
  },
  {
    label: "Quota",
    tag: "Skipped",
    tone: "gray",
    stmt: `${ACT_QUOTA.name} was out of quota, so it was skipped.`,
    note: "Quota is checked before the call, not after it fails.",
  },
  {
    label: "Fan-out",
    tag: "Merged",
    tone: "green",
    stmt: "One query. Three providers. One list.",
    note: "Duplicate URLs are merged and ranked with reciprocal rank fusion.",
  },
  {
    label: "API keys",
    tag: "Shown once",
    tone: "gray",
    code: "fs_live_8f2c…",
    note: "A project key is shown once. Revoke it and the next call gets a 401.",
  },
  {
    label: "Health",
    tag: "Degraded",
    tone: "amber",
    stmt: `${ACT_HEALTH.name} is slow today. It moves to the back of the line.`,
    note: "Healthy providers are always tried first.",
  },
  {
    label: "Projects",
    tag: "Isolated",
    tone: "green",
    stmt: "Two projects. Separate keys, logs and limits.",
    note: "Members only see the projects they belong to.",
  },
]

function Activity() {
  return (
    <div className="section-paper" data-theme="paper">
      <section className="section activity">
        <div className="container">
          <div className="how-head">
            <Reveal>
              <p className="eyebrow">Activity</p>
            </Reveal>
            <Reveal delay={0.06}>
              <h2 className="headline">
                <span className="hero-line">See every call.</span>
                <span className="hero-line">Down to the attempt.</span>
              </h2>
            </Reveal>
          </div>
          <div className="act-grid">
            {ACT_CARDS.map((c, i) => (
              <Reveal key={c.label} delay={0.05 * i} className="act-cell">
                <div className="act-card">
                  <div className="act-top">
                    <span className="act-label">{c.label}</span>
                    <span className={`tag-pill tag-${c.tone}`}>{c.tag}</span>
                  </div>
                  {c.code ? (
                    <code className="act-code">{c.code}</code>
                  ) : (
                    <p className="act-stmt">{c.stmt}</p>
                  )}
                  <p className="act-note">{c.note}</p>
                </div>
              </Reveal>
            ))}
          </div>
          <Reveal delay={0.2}>
            <p className="act-foot">Illustrative examples.</p>
          </Reveal>
        </div>
      </section>
    </div>
  )
}

/* ---------- projects split ---------- */

const PROJECT_POINTS: [string, string][] = [
  [
    "Members and roles",
    "Invite people and choose what each role can see and change.",
  ],
  [
    "Keys shown once",
    "Project API keys appear one time, then only their prefix.",
  ],
  [
    "Activity per project",
    "Every call is logged with its provider, latency and cost.",
  ],
  [
    "Share one key fairly",
    "Split a provider key's quota between projects.",
  ],
]

function Projects() {
  return (
    <div className="section-paper" data-theme="paper">
      <section className="section projects">
        <div className="container proj-grid">
          <Reveal className="proj-media">
            <div className="proj-img-card">
              <img src={projectsWide} alt="The Polyweb projects dashboard" />
            </div>
          </Reveal>
          <div className="proj-copy">
            <Reveal>
              <p className="eyebrow">Projects</p>
            </Reveal>
            <Reveal delay={0.06}>
              <h2 className="headline headline-split">
                <span className="hero-line">One gateway.</span>
                <span className="hero-line">Every team.</span>
              </h2>
            </Reveal>
            <ul className="proj-list">
              {PROJECT_POINTS.map(([h, p], i) => (
                <Reveal key={h} delay={0.1 + i * 0.05}>
                  <li>
                    <h3>{h}</h3>
                    <p>{p}</p>
                  </li>
                </Reveal>
              ))}
            </ul>
          </div>
        </div>
      </section>
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

function Agents() {
  const ref = useRef<HTMLDivElement>(null)
  const reduced = useReducedMotion()
  const inView = useInView(ref, { once: true, margin: "-20% 0px" })
  const show = inView || reduced
  return (
    <div className="section-night" id="agents" data-theme="night">
      <section className="section agents">
        <div className="container">
          <div className="how-head">
            <Reveal>
              <h2 className="headline">Built for agents.</h2>
            </Reveal>
            <Reveal delay={0.08}>
              <p className="subhead subhead-center">
                The MCP server runs over streamable HTTP and accepts project
                API keys. An agent searches and fetches inside its own
                project scopes
              </p>
            </Reveal>
          </div>
          <div className="agents-stage" ref={ref}>
            <motion.div
              className="agents-glow"
              aria-hidden="true"
              initial={reduced ? false : { opacity: 0 }}
              animate={show ? { opacity: 1 } : undefined}
              transition={{ duration: 0.8, ease: "easeOut" }}
            />
            <div className="agents-window">
              <div className="agents-titlebar" aria-hidden="true">
                <span className="agents-dot" />
                <span className="agents-dot" />
                <span className="agents-dot" />
              </div>
              <div className="agents-body">
                {AGENT_LINES.map(([kind, text], i) => (
                  <motion.div
                    key={i}
                    className={`agents-line-${kind}`}
                    initial={reduced ? false : { opacity: 0, y: 8 }}
                    animate={show ? { opacity: 1, y: 0 } : undefined}
                    transition={{ duration: 0.45, delay: 0.15 + i * 0.09, ease: EASE }}
                  >
                    {text}
                  </motion.div>
                ))}
              </div>
            </div>
          </div>
        </div>
      </section>
    </div>
  )
}

/* ---------- self-host ---------- */

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false)
  useEffect(() => {
    if (!copied) return
    const t = window.setTimeout(() => setCopied(false), 1600)
    return () => window.clearTimeout(t)
  }, [copied])
  return (
    <button
      type="button"
      className={`copy-btn${copied ? " copied" : ""}`}
      onClick={() => {
        navigator.clipboard?.writeText(text).then(
          () => setCopied(true),
          () => {}
        )
      }}
      aria-label={copied ? "Copied" : "Copy command"}
    >
      {copied ? "Copied" : "Copy"}
    </button>
  )
}

const SELFHOST_POINTS: [string, string][] = [
  ["One Compose file", "API, MCP server and dashboard come up together"],
  ["Keys encrypted at rest", "Provider keys live in an encrypted on-disk vault"],
  ["Never returned by the API", "No response ever contains secret material"],
]

function SelfHost() {
  return (
    <div className="section-paper" id="self-host" data-theme="paper">
      <section className="section selfhost">
        <div className="container selfhost-grid">
          <div>
            <Reveal>
              <p className="eyebrow">Self-host</p>
            </Reveal>
            <Reveal delay={0.06}>
              <h2 className="headline headline-split">
                <span className="hero-line">Your keys.</span>
                <span className="hero-line">Your machine.</span>
              </h2>
            </Reveal>
            <ul className="proj-list">
              {SELFHOST_POINTS.map(([h, p], i) => (
                <Reveal key={h} delay={0.1 + i * 0.05}>
                  <li>
                    <h3>{h}</h3>
                    <p>{p}</p>
                  </li>
                </Reveal>
              ))}
            </ul>
          </div>
          <Reveal className="selfhost-media" delay={0.15}>
            <div className="selfhost-card">
              <p className="selfhost-cmd">
                <span>docker compose up --build -d</span>
                <CopyButton text="docker compose up --build -d" />
              </p>
              <p className="selfhost-line">
                <span>Dashboard</span> {"http://<host>:3000"}
              </p>
              <p className="selfhost-line">
                <span>API</span> {"http://<host>:8001/docs"}
              </p>
              <p className="selfhost-line">
                <span>MCP</span> {"http://<host>:8000/mcp"}
              </p>
            </div>
          </Reveal>
        </div>
      </section>
    </div>
  )
}

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
      <Manifesto />
      <HowItWorks />
      <ProvidersSection />
      <Activity />
      <Projects />
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
