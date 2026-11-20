import brave from "./assets/brave.webp"
import exa from "./assets/exa.webp"
import firecrawl from "./assets/firecrawl.webp"
import keenable from "./assets/keenable.webp"
import parallel from "./assets/parallel.webp"
import tavily from "./assets/tavily.webp"
import tinyfish from "./assets/tinyfish.webp"
import youcom from "./assets/youcom.webp"

export interface Provider {
  id: string
  name: string
  src: string
  search: boolean
  fetch: boolean
}

// Capabilities mirror PROVIDER_SUPPORT_MASKS in
// src/polyweb/configuration/provider_config.py: everything does search +
// fetch except Brave, which is search only.
export const PROVIDERS: Provider[] = [
  { id: "brave", name: "Brave Search", src: brave, search: true, fetch: false },
  { id: "exa", name: "Exa", src: exa, search: true, fetch: true },
  { id: "firecrawl", name: "Firecrawl", src: firecrawl, search: true, fetch: true },
  { id: "tavily", name: "Tavily", src: tavily, search: true, fetch: true },
  { id: "parallel", name: "Parallel", src: parallel, search: true, fetch: true },
  { id: "you", name: "You.com", src: youcom, search: true, fetch: true },
  { id: "keenable", name: "Keenable", src: keenable, search: true, fetch: true },
  { id: "tinyfish", name: "Tinyfish", src: tinyfish, search: true, fetch: true },
]

export function pickRandom<T>(list: T[], n: number): T[] {
  const a = list.slice()
  for (let i = a.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1))
    const t = a[i]
    a[i] = a[j]
    a[j] = t
  }
  return a.slice(0, n)
}

export function capabilityLabel(p: Provider): string {
  return [p.search && "Search", p.fetch && "Fetch"].filter(Boolean).join(" · ")
}
