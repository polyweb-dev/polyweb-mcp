import { PageLayout, PageSection } from "./PageLayout"

const PROVIDERS: Array<[string, string]> = [
  ["Brave Search", "Search & Summarizer / Answers"],
  ["Exa", "Search & Content Fetch"],
  ["Firecrawl", "Web Scrape / Fetch"],
  ["Tavily", "Search & Extract"],
  ["Parallel", "Search & Fetch, with OAuth balance tracking"],
  ["You.com", "Search & Fetch"],
  ["Keenable", "Search — rolling-hour keyless tier, or API key"],
  ["Tinyfish", "Search & Markdown Fetch"],
]

export function ProvidersPage() {
  return (
    <PageLayout
      title="Providers"
      intro="Eight providers behind one request and response contract. You supply the credentials; Polyweb routes the calls."
    >
      <PageSection title="Supported providers">
        <table className="page-table">
          <tbody>
            {PROVIDERS.map(([name, caps]) => (
              <tr key={name}>
                <td>{name}</td>
                <td>{caps}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </PageSection>
      <PageSection title="Routing">
        <p>
          Every search or fetch runs through the routing layer. It can pick the
          best available provider automatically, honour a preferred or required
          provider, or fan out to several providers concurrently. If one
          provider fails, the next one answers — no manual retry.
        </p>
        <p>
          Keenable works without an API key on a rolling-hour keyless tier;
          every other provider needs credentials you enter once in the
          dashboard's encrypted vault.
        </p>
      </PageSection>
    </PageLayout>
  )
}
