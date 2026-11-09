import { Tag } from "./Tag"

const LABELS = {
  connected: "Connected",
  disconnected: "Disconnected",
  pending: "Pending",
  refresh_failed: "Refresh failed",
} as const

export function OAuthStatusTag({ status }: { status: keyof typeof LABELS | null }) {
  return <Tag tone={status === "connected" ? "success" : "warning"}>
    {status === null ? "Status unavailable" : LABELS[status]}
  </Tag>
}
