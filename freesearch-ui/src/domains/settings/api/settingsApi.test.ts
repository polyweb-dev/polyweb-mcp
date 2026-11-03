import { afterEach, describe, expect, it, vi } from "vitest"
import { installFetchStub, ok } from "@/test/fetchMock"
import {
  applySettingsCopy,
  getProjectSettings,
  previewSettingsCopy,
  settingsUpdateBody,
  updateProjectSettings,
} from "./settingsApi"

const RESOLUTION = { namespace: "settings", fields: {}, effective_settings: {}, provenance_by_field: {}, system_revision: 1, project_revision: 2 }
const PLAN = { source_project_id: "src", target_project_id: "tgt", mode: "overrides_only", source_revision: 4, target_revision: 2, system_revision: 1, fields: [{ field_id: "routing.max_attempts", section: "routing", attribute: "max_attempts", provenance: "project_override", value: 4, changed: true }], rejected: [], bindings: [], target: RESOLUTION }

describe("settingsUpdateBody", () => {
  it("groups changed fields by section, keeps null resets and the expected revision", () => {
    expect(settingsUpdateBody({ "trace.retention_days": 10, "trace.detail": null, "routing.max_attempts": 4 }, 7)).toEqual({
      expected_revision: 7,
      trace: { retention_days: 10, detail: null },
      routing: { max_attempts: 4 },
    })
  })
})

describe("settingsApi", () => {
  afterEach(() => vi.unstubAllGlobals())

  it("reads and writes one project's settings", async () => {
    const stub = installFetchStub(() => ok(RESOLUTION))
    const controller = new AbortController()
    await getProjectSettings("tgt", controller.signal)
    await updateProjectSettings("tgt", { "execution.cache_enabled": false }, 2)
    expect(stub.requests[0]?.url).toBe("/api/v1/projects/tgt/settings")
    expect(stub.requests[0]?.signal).toBe(controller.signal)
    expect(stub.requests[1]?.method).toBe("PUT")
    expect(stub.requests[1]?.body).toEqual({ expected_revision: 2, execution: { cache_enabled: false } })
  })

  it("previews and applies with the three revisions and binding versions", async () => {
    const stub = installFetchStub((req) =>
      ok(req.url.endsWith("/preview") ? PLAN : { ...PLAN, bindings_copied: ["nb1"], audit_event_id: "a1" })
    )
    const request = { sourceProjectId: "src", mode: "effective_snapshot" as const, sourceRevision: 4, targetRevision: 2, systemRevision: 1, bindingVersions: { b1: 3 } }
    await previewSettingsCopy("tgt", request)
    const result = await applySettingsCopy("tgt", request)
    const expected = {
      source_project_id: "src",
      expected_source_revision: 4,
      expected_target_revision: 2,
      expected_system_revision: 1,
      mode: "effective_snapshot",
      binding_versions: { b1: 3 },
    }
    expect(stub.requests[0]?.url).toBe("/api/v1/projects/tgt/settings/copy/preview")
    expect(stub.requests[0]?.body).toEqual(expected)
    expect(stub.requests[1]?.url).toBe("/api/v1/projects/tgt/settings/copy")
    expect(stub.requests[1]?.body).toEqual(expected)
    expect(result.bindingsCopied).toEqual(["nb1"])
    expect(result.settings.projectRevision).toBe(2)
  })
})
