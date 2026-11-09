import { PROJECT_ALPHA_ID } from "./accessFixtures"
import { ok } from "./fetchMock"
import type { RecordedRequest } from "./fetchMock"
import { projectProvidersFixture } from "./fixtures/projectProviders"

/** Project of the playground harness. */
export const PLAYGROUND_PROJECT_ID = PROJECT_ALPHA_ID

/** Provider view route of one project. */
export function projectProvidersUrl(projectId: string = PLAYGROUND_PROJECT_ID): string {
  return `/api/v1/projects/${projectId}/providers`
}

/**
 * Answer the playground's project provider view, or return `null`.
 *
 * Playground suites call it first in their fetch handler, so the picker sees
 * the canonical project view.
 */
export function answerProjectProviders(
  req: RecordedRequest,
  projectId: string = PLAYGROUND_PROJECT_ID
): Response | null {
  if (req.method !== "GET" || req.url !== projectProvidersUrl(projectId)) return null
  return ok(projectProvidersFixture(projectId))
}
