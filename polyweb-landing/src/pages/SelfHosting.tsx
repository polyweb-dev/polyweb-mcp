import { PageLayout, PageSection } from "./PageLayout"
import { GITHUB } from "../links"

export function SelfHostingPage() {
  return (
    <PageLayout
      title="Self-hosting"
      intro="One Compose file brings up the API, the MCP server and the dashboard."
    >
      <PageSection title="Run the stack">
        <pre className="code-block">{`git clone ${GITHUB}.git
cd polyweb-mcp
cp .env.example .env
docker compose up --build -d`}</pre>
        <p>That gives you:</p>
        <table className="page-table">
          <tbody>
            <tr>
              <td>:3000</td>
              <td>Dashboard (nginx)</td>
            </tr>
            <tr>
              <td>:8001</td>
              <td>REST API, with Swagger at /docs</td>
            </tr>
            <tr>
              <td>:8000/mcp</td>
              <td>MCP server over streamable HTTP</td>
            </tr>
          </tbody>
        </table>
      </PageSection>
      <PageSection title="State and secrets">
        <p>
          The API and MCP services share one SQLite database and one master-key
          file on the <code>polyweb-data</code> volume. On first start the
          containers generate a random 32-byte key and store it at{" "}
          <code>/data/.secret_key</code>, readable only by the container.
          Provider credentials go in through the dashboard's encrypted vault —
          never into <code>.env</code> or the Compose file.
        </p>
        <p>
          A plain <code>docker compose down</code> keeps your data and keys.{" "}
          <code>docker compose down -v</code> deletes the volume — and with it
          the database and master key — so back up{" "}
          <code>/data/.secret_key</code> before you do.
        </p>
      </PageSection>
    </PageLayout>
  )
}
