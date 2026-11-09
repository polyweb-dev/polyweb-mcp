import { PageLayout, PageSection } from "./PageLayout"

export function AboutPage() {
  return (
    <PageLayout
      title="About Polyweb"
      intro="Polyweb is a provider-neutral search, content extraction and quota-orchestration platform that you host yourself."
    >
      <PageSection title="One platform, three surfaces">
        <p>
          Polyweb aggregates multiple search and web-scraping providers behind a
          unified REST API, a Model Context Protocol (MCP) server and a React
          dashboard. The same execution path serves all three.
        </p>
      </PageSection>
      <PageSection title="Self-hosted">
        <p>
          A single Docker Compose stack brings up the API, the MCP server and
          the dashboard. State lives in one SQLite database, and provider
          credentials live in an encrypted vault — never in environment files.
        </p>
      </PageSection>
      <PageSection title="Provider-neutral">
        <p>
          Eight providers sit behind one request and response contract. Routing
          picks the best available provider per call, honours preferences, or
          fans out to several providers concurrently.
        </p>
      </PageSection>
    </PageLayout>
  )
}
