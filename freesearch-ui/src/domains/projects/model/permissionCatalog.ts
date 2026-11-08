export const PROJECT_PERMISSION_BITS = {
  search: 1,
  fetch: 2,
  traces: 4,
  usage: 8,
  settingsWrite: 16,
  settingsCopy: 32,
  providersConfigure: 64,
  tokens: 128,
  providerOwner: 32768,
} as const

export const DEVELOPER_BITS = 255
export const PERMISSION_PRESETS = { "Read only": 12, Standard: 15, "Full developer": 255 } as const

export const PERMISSION_COPY = {
  search: { bit: PROJECT_PERMISSION_BITS.search, label: "Run searches", description: "Send search requests in the playground" },
  fetch: { bit: PROJECT_PERMISSION_BITS.fetch, label: "Fetch pages", description: "Fetch web pages in the playground" },
  traces: { bit: PROJECT_PERMISSION_BITS.traces, label: "View activity", description: "Open request traces" },
  usage: { bit: PROJECT_PERMISSION_BITS.usage, label: "View usage", description: "See request counts" },
  settings_write: { bit: PROJECT_PERMISSION_BITS.settingsWrite, label: "Edit project settings", description: "Change the trace policy" },
  settings_copy: { bit: PROJECT_PERMISSION_BITS.settingsCopy, label: "Copy settings", description: "Copy settings from another project" },
  providers_configure: { bit: PROJECT_PERMISSION_BITS.providersConfigure, label: "Change provider order", description: "Change the Search and Fetch order and turn operations on or off" },
  tokens: { bit: PROJECT_PERMISSION_BITS.tokens, label: "Manage API keys", description: "Create, rotate and revoke project API keys" },
  provider_owner: { bit: PROJECT_PERMISSION_BITS.providerOwner, label: "Provider owner" },
} as const

export const PERMISSION_GROUPS = [
  { name: "Requests", items: [
    PERMISSION_COPY.search, PERMISSION_COPY.fetch,
  ] },
  { name: "Insight", items: [
    PERMISSION_COPY.traces, PERMISSION_COPY.usage,
  ] },
  { name: "Configuration", items: [
    PERMISSION_COPY.settings_write, PERMISSION_COPY.settings_copy, PERMISSION_COPY.providers_configure,
  ] },
  { name: "API keys", items: [
    PERMISSION_COPY.tokens,
  ] },
] as const

export const BASE_ACCESS = {
  label: "Base access",
  description: "See the project, its members, settings and providers. Every member has this access",
} as const

/** Count exactly the switches in the dialog, including always-on Base access. */
export function memberPermissionSummary(bits: number): string {
  const permissions = PERMISSION_GROUPS.flatMap<{ bit: number }>((group) => group.items)
  const enabled = permissions.filter((permission) => (bits & permission.bit) !== 0).length + 1
  return `${enabled} of ${permissions.length + 1} permissions`
}
