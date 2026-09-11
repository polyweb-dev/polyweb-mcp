// Compatibility shim (Slice 4): canonical primitives live in shared/ui.
// New code should import from @/shared/ui/PillTabs,
// @/shared/ui/PillTabsList, @/shared/ui/PillTabsPanel, or
// @/shared/ui/PillTabsContext directly.
export { PillTabs } from "@/shared/ui/PillTabs"
export type { PillTabsProps, PillTabOption } from "@/shared/ui/PillTabs"
export { PillTabsList } from "@/shared/ui/PillTabsList"
export { PillTabsPanel } from "@/shared/ui/PillTabsPanel"
export type { PillTabsPanelProps } from "@/shared/ui/PillTabsPanel"
