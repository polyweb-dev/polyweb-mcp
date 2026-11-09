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
    { text: "Add provider capacity", to: providersPath, done: hasCredential },
    { text: "Turn on search or fetch for a provider", to: providersPath, done: hasEffective },
    { text: "Run a first search", to: `/p/${projectId}/playground`, done: false },
  ]
  return (
    <section aria-labelledby="project-setup-heading" className="fs-panel p-4">
      <h3 id="project-setup-heading" className="fs-section-title">
        Set up this project
      </h3>
      {canConfigure ? (
        <>
          <p className="fs-section-description">
            Searches and fetches fail until a provider route can run them.
          </p>
          <ol className="mt-3 space-y-1">
            {steps.map((step, index) => (
              <li key={step.text} className="flex h-7 items-center gap-3 text-[13px]">
                <span
                  aria-hidden="true"
                  className={
                    step.done
                      ? "grid size-5 place-items-center rounded-full bg-[var(--signal)] text-white"
                      : "fs-keycap size-5 min-w-5 rounded-full"
                  }
                >
                  {step.done ? <Check className="size-3" strokeWidth={2.5} /> : index + 1}
                </span>
                {step.done ? (
                  <span className="text-[var(--muted)] line-through decoration-[var(--muted)]/50">
                    <span className="sr-only">Done: </span>
                    {step.text}
                  </span>
                ) : (
                  <Link to={step.to} className="fs-link">
                    {step.text}
                  </Link>
                )}
              </li>
            ))}
          </ol>
        </>
      ) : (
        <p className="fs-section-description">Ask a project admin to set up a provider</p>
      )}
    </section>
  )
}
