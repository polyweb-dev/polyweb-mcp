import { Check } from "lucide-react"
import { Link } from "react-router"

/**
 * First-use guide of one unconfigured project.
 *
 * It appears while the provider view is ready and no provider has effective
 * operations. Step one is done once any credential (project-owned or granted)
 * exists; step two once any provider can execute. Without `providers.configure`
 * the actions become an ask-an-admin hint instead of links.
 */
export function ProjectSetupChecklist({
  projectId,
  canConfigure,
  hasCredential,
  hasEffective,
}: {
  projectId: string
  canConfigure: boolean
  hasCredential: boolean
  hasEffective: boolean
}) {
  const providersPath = `/p/${projectId}/providers`
  const steps = [
    { text: "Add a provider key", to: providersPath, done: hasCredential },
    { text: "Turn on search or fetch for a provider", to: providersPath, done: hasEffective },
    { text: "Run a first search", to: `/p/${projectId}/playground`, done: false },
  ]
  return (
    <section className="space-y-2 rounded border border-[var(--border-subtle)] px-4 py-3">
      <h3 className="text-[13px] font-medium text-[var(--text-strong)]">Set up this project</h3>
      {canConfigure ? (
        <ol className="list-decimal space-y-1 pl-5 text-[13px]">
          {steps.map((step) => (
            <li key={step.text}>
              {step.done ? (
                <span className="inline-flex items-center gap-1 text-[var(--muted)]">
                  <Check aria-hidden="true" className="size-4" />
                  <span className="sr-only">Done: </span>
                  {step.text}
                </span>
              ) : (
                <Link to={step.to} className="text-[var(--signal)] hover:underline">
                  {step.text}
                </Link>
              )}
            </li>
          ))}
        </ol>
      ) : (
        <p className="text-[13px] text-[var(--muted)]">
          Ask a project admin to set up a provider.
        </p>
      )}
    </section>
  )
}
