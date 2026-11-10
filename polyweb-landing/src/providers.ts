import brave from "./assets/brave.webp"
import exa from "./assets/exa.webp"
import firecrawl from "./assets/firecrawl.webp"
import keenable from "./assets/keenable.webp"
import parallel from "./assets/parallel.webp"
import tavily from "./assets/tavily.webp"
import tinyfish from "./assets/tinyfish.webp"
import youcom from "./assets/youcom.webp"

export interface Provider {
  name: string
  src: string
  search: boolean
  fetch: boolean
}

export const PROVIDERS: Provider[] = [
  { name: "Brave Search", src: brave, search: true, fetch: false },
  { name: "Exa", src: exa, search: true, fetch: true },
  { name: "Firecrawl", src: firecrawl, search: true, fetch: true },
  { name: "Tavily", src: tavily, search: true, fetch: true },
  { name: "Parallel", src: parallel, search: true, fetch: true },
  { name: "You.com", src: youcom, search: true, fetch: true },
  { name: "Keenable", src: keenable, search: true, fetch: false },
  { name: "Tinyfish", src: tinyfish, search: true, fetch: true },
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
