/**
 * Application route table. Workspace route identifiers live here in app
 * routing, not in the visual Sidebar component. Redirects (root, legacy
 * /providers, unknown paths) stay verbatim in DashboardShell's Routes
 * table so the legacy targets are pinned exactly once.
 */

export type TabId =
  | "playground"
  | "routing"
  | "quotas"
  | "activity"
  | "settings"

export const TAB_PATHS: Record<TabId, string> = {
  playground: "/playground",
  routing: "/routing",
  quotas: "/usage",
  activity: "/activity",
  settings: "/settings",
}

export interface WorkspaceRoute {
  id: TabId
  path: string
}

export const workspaceRoutes: WorkspaceRoute[] = [
  { id: "playground", path: TAB_PATHS.playground },
  { id: "routing", path: TAB_PATHS.routing },
  { id: "quotas", path: TAB_PATHS.quotas },
  { id: "activity", path: TAB_PATHS.activity },
  { id: "settings", path: TAB_PATHS.settings },
]
