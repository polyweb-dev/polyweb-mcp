import { PageLayout, PageSection } from "./PageLayout"

export function FetchApiPage() {
  return (
    <PageLayout
      title="Fetch API"
      intro="One POST endpoint that fetches a URL's content through the best available provider."
    >
      <PageSection title="Request">
        <p>
          <code>POST /fetch</code> on the API port —{" "}
          <code>http://&lt;host&gt;:8001/fetch</code>. Authenticate with a
          project API key sent as{" "}
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
              <td>url</td>
              <td>string</td>
              <td>Required. The http(s) URL to fetch.</td>
            </tr>
            <tr>
              <td>max_chars</td>
              <td>integer</td>
              <td>Optional. Cap the returned content at 1–2,000,000 characters.</td>
            </tr>
            <tr>
              <td>json_extract</td>
              <td>boolean</td>
              <td>Optional. Ask the provider for structured extraction.</td>
            </tr>
            <tr>
              <td>zero_data_retention</td>
              <td>boolean</td>
              <td>Optional. Request zero data retention from the provider.</td>
            </tr>
            <tr>
              <td>routing</td>
              <td>object</td>
              <td>
                Optional. Same routing preference object as{" "}
                <code>POST /search</code>.
              </td>
            </tr>
          </tbody>
        </table>
      </PageSection>
      <PageSection title="Example">
        <pre className="code-block">{`curl http://<host>:8001/fetch \\
  -H "Authorization: Bearer fs_live_..." \\
  -H "Content-Type: application/json" \\
  -d '{"url": "https://example.com/article"}'`}</pre>
      </PageSection>
      <PageSection title="Response">
        <p>
          A <code>FetchResponse</code> names the <code>provider</code> that
          answered and carries one <code>document</code>: the fetched{" "}
          <code>url</code>, its <code>content</code>, optional{" "}
          <code>title</code>, <code>content_type</code>,{" "}
          <code>fetched_at</code> timestamp and <code>metadata</code>. A{" "}
          <code>usage</code> event is included when the provider reports
          metering.
        </p>
      </PageSection>
    </PageLayout>
  )
}
