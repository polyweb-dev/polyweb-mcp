import { PageLayout, PageSection } from "./PageLayout"

export function McpPage() {
  return (
    <PageLayout
      title="MCP server"
      intro="The same search and fetch execution path, exposed to coding agents over the Model Context Protocol."
    >
      <PageSection title="Connect over streamable HTTP">
        <p>
          Point an MCP client at <code>http://&lt;host&gt;:8000/mcp</code>:
        </p>
        <pre className="code-block">{`{ "type": "streamable-http", "url": "http://<host>:8000/mcp" }`}</pre>
      </PageSection>
      <PageSection title="Tools">
        <p>
          Two tools are registered: <code>search</code>, which takes the same
          request body as <code>POST /search</code>, and <code>fetch</code>,
          which takes the same request body as <code>POST /fetch</code>. The MCP
          transport exposes only these tools — nothing else.
        </p>
      </PageSection>
      <PageSection title="Authentication">
        <p>
          The MCP server accepts only project API keys, sent in the request's{" "}
          <code>Authorization</code> header, and verifies the key on every tool
          call. A call without a valid key is rejected before any provider
          access.
        </p>
        <p>
          A stdio transport exists as a local-only escape hatch on the machine
          that runs the daemon:{" "}
          <code>
            docker exec -i polyweb-mcp uv run polyweb-mcp --transport stdio
          </code>
          . It reads the key from <code>POLYWEB_MCP_BEARER_TOKEN</code>. For
          every remote agent, use the streamable-HTTP URL above.
        </p>
      </PageSection>
    </PageLayout>
  )
}
