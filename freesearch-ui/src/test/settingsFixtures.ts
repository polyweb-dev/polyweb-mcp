/** Backend `SettingsResolution` wire fixtures for the settings page tests. */

type Provenance = "system_default" | "project_override" | "system_constrained"

interface FieldSeed {
  value: unknown
  systemDefault?: unknown
  override?: unknown
  provenance?: Provenance
  limit?: unknown
  constraintApplied?: boolean
  overrideAllowed?: boolean
}

const DEFAULT_SEEDS: Record<string, FieldSeed> = {
  "routing.fallback_policy": { value: "chained" },
  "routing.cost_optimization_preset": { value: "balanced" },
  "routing.max_attempts": { value: 3 },
  "routing.preferred_providers": { value: [] },
  "execution.cache_enabled": { value: true },
  "execution.default_timeout_seconds": { value: 30, limit: 300 },
  "execution.max_fanout_concurrency": { value: 5, limit: 20 },
  "execution.cache_ttl_seconds": { value: 300 },
  "trace.sampling_rate": { value: 1 },
  "trace.detail": { value: "metadata", limit: "metadata" },
  "trace.payload_redaction": { value: "standard", limit: "standard" },
  "trace.retention_days": { value: 30, limit: 90 },
  "system.max_trace_retention_days": { value: 90, overrideAllowed: false },
}

function fieldWire(id: string, seed: FieldSeed) {
  const section = id.startsWith("system.") ? "safety_limits" : (id.split(".")[0] ?? "")
  const override = seed.override ?? null
  return {
    field_name: id,
    section,
    effective_value: seed.value,
    provenance: seed.provenance ?? (override === null ? "system_default" : "project_override"),
    is_null: false,
    system_default: seed.systemDefault ?? (override === null ? seed.value : seed.systemDefault),
    project_override: override,
    source_scope: override === null ? "system" : "project",
    override_allowed: seed.overrideAllowed ?? true,
    system_safety_limit: seed.limit ?? null,
    constraint_applied: seed.constraintApplied ?? false,
  }
}

/** One project's resolved settings; `seeds` replace the default field values. */
export function settingsResolutionFixture(options: {
  projectId: string
  projectRevision?: number
  systemRevision?: number
  seeds?: Record<string, FieldSeed>
}) {
  const seeds = { ...DEFAULT_SEEDS, ...options.seeds }
  const fields = Object.fromEntries(Object.entries(seeds).map(([id, seed]) => [id, fieldWire(id, seed)]))
  return {
    namespace: "settings",
    fields,
    effective_settings: {},
    provenance_by_field: {},
    system_revision: options.systemRevision ?? 1,
    project_revision: options.projectRevision ?? 4,
    project_id: options.projectId,
    schema_version: 1,
    overrides: {},
  }
}
