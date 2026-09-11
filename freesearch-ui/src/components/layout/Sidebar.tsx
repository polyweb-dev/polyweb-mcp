// Compatibility shim (Slice 4): canonical sidebar lives in app/layout,
// route identifiers live in app/routes. Sidebar navigation ownership moved
// to app routing; this module only re-exports the new owners.
export { Sidebar } from "@/app/layout/Sidebar"
export type { SidebarProps } from "@/app/layout/Sidebar"
export type { TabId } from "@/app/routes"
