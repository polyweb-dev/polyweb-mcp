import { PageLayout, PageSection } from "./PageLayout"
import { GITHUB } from "../links"

export function SecurityPage() {
  return (
    <PageLayout
      title="Security"
      intro="Provider credentials live in an encrypted vault. No response ever contains secret material."
    >
      <PageSection title="Provider keys">
        <p>
          Provider API keys are entered once through the dashboard and stored
          in an encrypted vault in the database — each secret in its own
          AES-GCM envelope under a master key that lives outside the database
          (the <code>/data/.secret_key</code> file in Docker, or the configured{" "}
          <code>POLYWEB_ENCRYPTION_KEY_FILE</code>). Credentials are never read
          from <code>.env</code> and never appear in any API response — not the
          secret, its slot name or its digest.
        </p>
      </PageSection>
      <PageSection title="Project API keys">
        <p>
          Machine-facing keys (<code>fs_live_…</code>) are stored as SHA-256
          verifiers; the raw key is returned only at creation or rotation. A
          key carries only <code>search.execute</code> and/or{" "}
          <code>fetch.execute</code> scopes inside one project, is checked on
          every request and tool call, and can be rotated or revoked at any
          time.
        </p>
      </PageSection>
      <PageSection title="Threat model">
        <p>
          The repository includes an adversarial threat model for the Parallel
          provider's OAuth device flow. It pins down the expected behaviour —
          no token material in logs, responses or database rows; revocation
          before deletion on disconnect; single-flight token refresh; and
          Decimal-exact balance reporting — each backed by covering tests.
        </p>
        <p>
          <a
            href={`${GITHUB}/blob/main/docs/THREAT_MODEL.md`}
            target="_blank"
            rel="noreferrer"
          >
            Read the threat model on GitHub
          </a>
        </p>
      </PageSection>
    </PageLayout>
  )
}
