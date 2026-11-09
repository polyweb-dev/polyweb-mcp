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
          View on GitHub
        </a>
      </div>
    </header>
  )
}
