import { requestJson } from "@/shared/api/client"
import { decodeProjectOrder } from "../model/projectOrder"
import type { OrderOperation, OrderStrategy, ProjectOrder } from "../model/projectOrder"

export interface OrderUpdate {
  strategy: OrderStrategy
  order?: string[]
}

function orderPath(projectId: string): string {
  return `/api/v1/projects/${encodeURIComponent(projectId)}/routing/order`
}

export async function getProjectOrder(projectId: string, signal?: AbortSignal): Promise<ProjectOrder> {
  return decodeProjectOrder(await requestJson<unknown>(orderPath(projectId), { signal }))
}

export async function putProjectOrder(projectId: string, operation: OrderOperation, update: OrderUpdate): Promise<ProjectOrder> {
  return decodeProjectOrder(await requestJson<unknown>(`${orderPath(projectId)}/${operation}`, {
    method: "PUT",
    body: JSON.stringify(update),
  }))
}
