import { Link } from "react-router"

/**
 * First-use guidance: the project has no provider that can run the active
 * operation. The link leads to the provider setup page of the URL project.
 */
export function ProviderSetupNotice({ projectId }: { projectId: string }) {
  return (
    <p
      role="status"
      className="rounded border border-[var(--border-subtle)] px-3 py-2 text-[13px] text-[var(--text)]"
    >
      No provider is set up for this project.{" "}
      <Link to={`/p/${projectId}/providers`} className="text-[var(--signal)] hover:underline">
        Set up providers
      </Link>
    </p>
  )
}
