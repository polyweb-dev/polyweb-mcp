import { PageLayout, PageSection } from "./PageLayout"

export function ProjectsPage() {
  return (
    <PageLayout
      title="Projects and keys"
      intro="Projects group members, API keys and usage. Machine clients authenticate with project API keys, not user accounts."
    >
      <PageSection title="Members and roles">
        <p>
          Project authority comes only from an active project membership. Every
          project keeps at least one active <code>project_admin</code>;{" "}
          <code>project_member</code> covers day-to-day work, and the extra{" "}
          <code>routing_editor</code>, <code>provider_editor</code> and{" "}
          <code>token_manager</code> roles grant narrower permissions.
          Installation-wide controls sit with a separate{" "}
          <code>system_admin</code> assignment that confers no project
          membership.
        </p>
      </PageSection>
      <PageSection title="Project API keys">
        <p>
          Keys look like <code>fs_live_&lt;prefix&gt;_&lt;secret&gt;</code>. The
          12-character prefix is public and identifies the key in lists and
          audit records; only a SHA-256 verifier of the secret is stored, so
          the raw key is returned exactly once — in the creation or rotation
          response. Send it only as{" "}
          <code>Authorization: Bearer &lt;key&gt;</code>, never in a URL.
        </p>
        <p>
          A key belongs to one project and holds only{" "}
          <code>search.execute</code> and/or <code>fetch.execute</code> scopes —
          it never inherits any role of the person who created it. Keys default
          to a 90-day lifetime, can be issued without expiry, and can be
          rotated with an overlap window or revoked at any time. The key is
          verified again on every request and every MCP tool call.
        </p>
      </PageSection>
      <PageSection title="Activity and usage">
        <p>
          Every search and fetch produces a usage event and a trace, recorded
          per project — which provider answered, latency, cost and outcome —
          so activity is visible per key and per project.
        </p>
      </PageSection>
      <PageSection title="Pooled capacity">
        <p>
          Upstream provider capacity is organised into pools. Only system
          administrators manage pools and grant each project an allocation — a
          strict base rate by default, with optional borrowing of idle capacity
          up to a maximum rate.
        </p>
      </PageSection>
    </PageLayout>
  )
}
