/**
 * Read the safe credential metadata that a project can see.
 */
import { requestJson } from "@/shared/api/client"
import { decodeList } from "@/shared/api/decode"
import { decodeProjectCredential } from "./credentialsWire"
import type { ProjectCredential } from "../model/credentials"

function segment(value: string): string {
  return encodeURIComponent(value)
}

function signalInit(signal?: AbortSignal): RequestInit {
  return signal === undefined ? {} : { signal }
}

/** List the credentials one project can see. */
export async function listProjectCredentials(
  projectId: string,
  signal?: AbortSignal
): Promise<ProjectCredential[]> {
  const payload = await requestJson<unknown>(
    `/api/v1/projects/${segment(projectId)}/credentials`,
    signalInit(signal)
  )
  return decodeList(payload, decodeProjectCredential, "project credential list")
}
