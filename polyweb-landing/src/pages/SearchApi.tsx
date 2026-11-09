import { PageLayout, PageSection } from "./PageLayout"

export function SearchApiPage() {
  return (
    <PageLayout
      title="Search API"
      intro="One POST endpoint that runs a web search through the best available provider — or several providers concurrently."
    >
      <PageSection title="Request">
        <p>
          <code>POST /search</code> on the API port —{" "}
          <code>http://&lt;host&gt;:8001/search</code> in the default Compose
          setup. Calls are authenticated with a project API key sent as{" "}
          <code>Authorization: Bearer fs_live_…</code>. With a key,{" "}
          <code>project_id</code> is optional and, when given, must name the
          key's project.
        </p>
        <table className="page-table">
          <thead>
            <tr>
              <th>Field</th>
              <th>Type</th>
              <th>Notes</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>query</td>
              <td>string</td>
              <td>Required. 1–2000 characters.</td>
            </tr>
            <tr>
              <td>limit</td>
              <td>integer</td>
              <td>1–100, default 10.</td>
            </tr>
            <tr>
              <td>language</td>
              <td>string</td>
              <td>Optional. 2–16 characters.</td>
            </tr>
            <tr>
              <td>country_code</td>
              <td>string</td>
              <td>Optional. 2 characters.</td>
            </tr>
            <tr>
              <td>domains</td>
              <td>string[]</td>
              <td>Optional. Restrict results to these domains.</td>
            </tr>
            <tr>
              <td>routing</td>
              <td>object</td>
              <td>
                Optional. Routing preference: <code>mode</code> (
                <code>auto</code>, <code>prefer</code>, <code>require</code>,{" "}
                <code>fanout</code>), <code>providers</code>,{" "}
                <code>allow_fallback</code>, <code>binding_id</code>.
              </td>
            </tr>
            <tr>
              <td>fanout</td>
              <td>boolean</td>
              <td>Optional. Query several providers concurrently.</td>
            </tr>
          </tbody>
        </table>
      </PageSection>
      <PageSection title="Example">
        <pre className="code-block">{`curl http://<host>:8001/search \\
  -H "Authorization: Bearer fs_live_..." \\
  -H "Content-Type: application/json" \\
  -d '{"query": "latest climate research", "limit": 10}'`}</pre>
      </PageSection>
      <PageSection title="Response">
        <p>
          A <code>SearchResponse</code> echoes the <code>query</code>, names the{" "}
          <code>provider</code> that answered, lists{" "}
          <code>participating_providers</code>, and carries a{" "}
          <code>waterfall</code> trace with one entry per attempted provider —
          <code>latency_ms</code>, <code>status</code>,{" "}
          <code>results_count</code>, <code>cost_credits</code> and{" "}
          <code>error</code>. Each entry in <code>results</code> is a{" "}
          <code>SearchResult</code>: <code>title</code>, <code>url</code>,{" "}
          <code>snippet</code>, optional <code>published_at</code>,{" "}
          <code>source</code>, <code>score</code> (0–1), <code>sources</code>{" "}
          and <code>metadata</code>. A <code>usage</code> event and{" "}
          <code>total_results</code> are included when the provider reports
          them.
        </p>
      </PageSection>
    </PageLayout>
  )
}
