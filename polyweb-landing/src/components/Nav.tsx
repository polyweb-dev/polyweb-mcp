import { useEffect, useState } from "react"
import logo from "../assets/polyweb.webp"
import { GITHUB } from "../links"

export function Nav({ page = false }: { page?: boolean }) {
  const [observed, setObserved] = useState<"night" | "paper">("night")
  const theme = page ? "night" : observed

  useEffect(() => {
    if (page) return
    const sections = document.querySelectorAll<HTMLElement>("[data-theme]")
    const visible = new Map<Element, number>()
    const pick = () => {
      let best: Element | null = null
      let bestTop = Infinity
      for (const [el] of visible) {
        const r = el.getBoundingClientRect()
        if (r.top <= 64 && r.bottom > 64) {
          best = el // the section directly under the nav wins
          break
        }
        const top = Math.abs(r.top)
        if (top < bestTop) {
          bestTop = top
          best = el
        }
      }
      if (best) {
        setObserved(
          (best as HTMLElement).dataset.theme === "paper" ? "paper" : "night"
        )
      }
    }
    const observer = new IntersectionObserver(
      (entries) => {
        for (const e of entries) {
          if (e.isIntersecting) visible.set(e.target, e.intersectionRatio)
          else visible.delete(e.target)
        }
        pick()
      },
      { rootMargin: "-48px 0px 0px 0px" }
    )
    sections.forEach((s) => observer.observe(s))
    return () => observer.disconnect()
  }, [page])

  return (
    <header className={`nav nav-${theme}`}>
      <div className="nav-inner">
        <a className="nav-brand" href="#top" aria-label="Polyweb home">
          <img src={logo} alt="" width={26} height={26} />
          Polyweb
        </a>
        <nav className="nav-links" aria-label="Sections">
          <a href="#features">Features</a>
          <a href="#agents">For agents</a>
          <a href="#self-host">Self-host</a>
          <a href="#/search-api">Docs</a>
        </nav>
        <a
          className="button button-secondary-dark button-nav"
          href={GITHUB}
          target="_blank"
          rel="noreferrer"
        >
          <svg
            width="16"
            height="16"
            viewBox="0 0 16 16"
            fill="currentColor"
            aria-hidden="true"
            style={{ marginRight: 8 }}
          >
            <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27s1.36.09 2 .27c1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.01 8.01 0 0 0 16 8c0-4.42-3.58-8-8-8Z" />
          </svg>
          View on GitHub
        </a>
      </div>
    </header>
  )
}
