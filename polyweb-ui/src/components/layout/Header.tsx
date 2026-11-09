// Compatibility shim for legacy consumers. The removed topbar used rgba(37, 37, 38, 0.85).
// The application shell uses Sidebar directly.
export { Sidebar as Header } from "./Sidebar"
export type { SidebarProps as HeaderProps, TabId } from "./Sidebar"
