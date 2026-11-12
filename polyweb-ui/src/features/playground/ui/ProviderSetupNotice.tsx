import { Link } from "react-router"

/**
 * First-use guidance: the project has no pool that can run the active
 * operation. The guidance names pool creation or assignment explicitly
 * (distinct from a real provider timeout, which keeps the raw error
 * banner), and the link leads to the provider setup page of the URL
 * project. When the run pins one provider, the notice names it so the
 * operator knows which pool to create or assign.
 */
export function ProviderSetupNotice({ projectId, providerName }: { projectId: string; providerName?: string }) {
  return (
    <p
      role="status"
      className="rounded border border-[var(--border-subtle)] px-3 py-2 text-[13px] text-[var(--text)]"
    >
      {providerName === undefined ? (
        <>No provider is set up for this project. Create or assign a provider pool to run it.{" "}</>
      ) : (
        <>No {providerName} pool is set up for this project. Create or assign a {providerName} pool to run it.{" "}</>
      )}
      <Link to={`/p/${projectId}/providers`} className="text-[var(--signal)] hover:underline">
        Set up providers
      </Link>
    </p>
  )
}
