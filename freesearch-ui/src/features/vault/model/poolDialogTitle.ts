export function poolDialogTitle(mode: "edit" | "capacity" | "create", provider: string): string {
  if (mode === "edit") return "Edit pool"
  if (mode === "create") return "Create pool"
  return `Add ${provider} capacity`
}
