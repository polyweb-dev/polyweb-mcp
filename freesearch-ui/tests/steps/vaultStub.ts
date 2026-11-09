import type { Page, Route } from "@playwright/test"

type Operation = "search" | "fetch"
type Strategy = "free_first" | "lowest_cost" | "custom"
type Body = Record<string, unknown>

interface Key {
  id: string
  provider_type: string
  label: string
  auth_mode: string
  status: string
  generation: number
  created_at: string
  capacity: unknown
  overcommit: boolean
  contention_mode: string
}

interface Pool {
  id: string
  credential_id: string
  project_id: string | null
  provider_type: string
  label: string
  rate: unknown
  budget: unknown
  budget_used_usd: number
  operations: Operation[]
  operation_limits: unknown
}

interface Bridge {
  projects(): { id: string; name: string }[]
  access(id: string): boolean
  account(): { user_id: string; email: string }
  owner(project: string): { user_id: string; email: string } | null
  member(project: string, user: string): { user_id: string; email: string; activeAdmin: boolean } | null
}

const keys: Key[] = []
const pools: Pool[] = []
const strategies = new Map<string, { strategy: Strategy; order: string[] }>()
const oauth = new Map<string, string>()
const owners = new Map<string, { user_id: string; email: string }>()
const balances = new Map<string, { remaining: string; native_unit: string; observed_at: string }>()
let sequence = 0
let revision = 1

export function resetVaultStub(): void {
  keys.length = 0
  pools.length = 0
  strategies.clear()
  oauth.clear()
  owners.clear()
  balances.clear()
  sequence = 0
  revision = 1
}

export function seedVaultBalance(provider: string, label: string, remaining: string, unit: string): void {
  const key = createKey({ provider_type: provider, label, auth_mode: "api_key" })
  balances.set(key.id, { remaining, native_unit: unit, observed_at: "2026-10-01T09:00:00Z" })
}

export function vaultOwner(project: string, fallback: { user_id: string; email: string } | null): { user_id: string; email: string } | null {
  return owners.get(project) ?? fallback
}

export function approveVaultOAuth(label: string): void {
  const key = keys.find((item) => item.label === label)
  if (!key) throw new Error(`Unknown vault key: ${label}`)
  oauth.set(key.id, "connected")
}

function id(): string {
  sequence += 1
  return `a0000000-0000-4000-8000-${String(sequence).padStart(12, "0")}`
}

function body(route: Route): Body {
  try {
    return route.request().postDataJSON() as Body
  } catch {
    return {}
  }
}

function json(route: Route, value: unknown, status = 200): Promise<void> {
  return route.fulfill({ status, contentType: "application/json", body: JSON.stringify(value) })
}

function keyRead(key: Key): Key & { pool_count: number } {
  return { ...key, pool_count: pools.filter((pool) => pool.credential_id === key.id).length }
}

function createKey(input: Body): Key {
  const key: Key = {
    id: id(), provider_type: String(input.provider_type), label: String(input.label),
    auth_mode: String(input.auth_mode ?? "api_key"), status: "active", generation: 1,
    created_at: "2026-01-01T00:00:00Z", capacity: input.capacity ?? null,
    overcommit: input.overcommit !== false, contention_mode: String(input.contention_mode ?? "equal"),
  }
  keys.push(key)
  return key
}

function createPool(key: Key, input: Body): Pool {
  const rate = typeof input.rate === "object" && input.rate !== null ? input.rate as Body : {}
  const budget = typeof input.budget === "object" && input.budget !== null ? input.budget as Body : null
  const pool: Pool = {
    id: id(), credential_id: key.id, provider_type: key.provider_type,
    project_id: typeof input.project_id === "string" ? input.project_id : null,
    label: String(input.label), rate: { limit: rate.limit ?? null, window_seconds: rate.window_seconds ?? 60 },
    budget: budget === null ? null : { limit: budget.limit, period: budget.period ?? "month" }, budget_used_usd: 0,
    operations: Array.isArray(input.operations) ? input.operations as Operation[] : ["search", "fetch"],
    operation_limits: input.operation_limits ?? null,
  }
  pools.push(pool)
  revision += 1
  return pool
}

function projectPool(pool: Pool, bridge: Bridge): Body {
  return {
    pool_id: pool.id, label: pool.label, provider_type: pool.provider_type,
    key_label: keys.find((key) => key.id === pool.credential_id)?.label ?? "",
    owner: vaultOwner(pool.project_id ?? "", bridge.owner(pool.project_id ?? "")) ?? bridge.account(),
    rate: pool.rate, budget: pool.budget,
    budget_used: pool.budget_used_usd, operations: pool.operations,
  }
}

function orderFor(project: string, operation: Operation): Body {
  const selected = pools.filter((pool) => pool.project_id === project && pool.operations.includes(operation))
  const rows = [
    ...selected.map((pool) => ({
      provider: pool.provider_type, name: pool.provider_type === "brave" ? "Brave Search" : pool.provider_type,
      call_cost_usd: "0.005", keyless: false,
    })),
    { provider: "keenable", name: "Keenable", call_cost_usd: "0", keyless: true },
  ]
  const saved = strategies.get(`${project}:${operation}`)
  const strategy = saved?.strategy ?? "custom"
  if (strategy === "free_first" || strategy === "lowest_cost") rows.sort((a, b) => Number(a.call_cost_usd) - Number(b.call_cost_usd))
  else if (saved?.order.length) rows.sort((a, b) => saved.order.indexOf(a.provider) - saved.order.indexOf(b.provider))
  const notAllowed = pools
    .filter((pool) => pool.project_id === project && !pool.operations.includes(operation))
    .map((pool) => pool.provider_type)
    .filter((provider) => !rows.some((row) => row.provider === provider))
  return { strategy, providers: rows, has_saved_custom: Boolean(saved?.order.length), not_allowed: notAllowed }
}

function order(project: string): Body {
  return { revision, search: orderFor(project, "search"), fetch: orderFor(project, "fetch") }
}

function handleKeys(route: Route, parts: string[], method: string): Promise<void> {
  const key = keys.find((item) => item.id === parts[0])
  const input = body(route)
  if (!parts.length && method === "GET") return json(route, keys.map(keyRead))
  if (!parts.length && method === "POST") return json(route, keyRead(createKey(input)), 201)
  if (!key) return json(route, { detail: "Not found" }, 404)
  if (parts[1] === "pools") {
    if (method === "GET") return json(route, pools.filter((pool) => pool.credential_id === key.id))
    if (method === "POST") return json(route, createPool(key, input), 201)
  }
  if (parts[1] === "rotate" && method === "POST") {
    if (input.expected_generation !== key.generation) return json(route, { detail: "Conflict" }, 409)
    key.generation += 1
    return json(route, keyRead(key))
  }
  if (parts[1] === "oauth") return handleOAuth(route, key, parts[2], method)
  if (parts.length === 1 && method === "PATCH") {
    for (const field of ["label", "capacity", "overcommit", "contention_mode"] as const) {
      if (field in input) Object.assign(key, { [field]: input[field] })
    }
    return json(route, keyRead(key))
  }
  if (parts.length === 1 && method === "DELETE") {
    const deleted = pools.filter((pool) => pool.credential_id === key.id)
    for (const pool of deleted) pools.splice(pools.indexOf(pool), 1)
    keys.splice(keys.indexOf(key), 1)
    revision += 1
    return json(route, { deleted_pools: deleted.map(({ id: poolId, project_id }) => ({ id: poolId, project_id })) })
  }
  return json(route, { detail: "Not found" }, 404)
}

function handleOAuth(route: Route, key: Key, action: string | undefined, method: string): Promise<void> {
  if (action === "device" && method === "POST") {
    oauth.set(key.id, "pending")
    return json(route, { user_code: "WXYZ-1234", verification_uri: "https://parallel.example/device", interval: 1, expires_in: 600 })
  }
  if (method === "DELETE") {
    oauth.set(key.id, "disconnected")
    return json(route, {})
  }
  if (method === "GET" || (action === "poll" && method === "POST")) {
    return json(route, { status: oauth.get(key.id) ?? "disconnected", interval: 1 })
  }
  return json(route, { detail: "Not found" }, 404)
}

function handlePools(route: Route, parts: string[], method: string): Promise<void> {
  const pool = pools.find((item) => item.id === parts[0])
  const input = body(route)
  if (!pool) return json(route, { detail: "Not found" }, 404)
  if (parts.length === 1 && method === "GET") return json(route, pool)
  if (parts[1] === "assign" && method === "POST") pool.project_id = String(input.project_id)
  else if (parts[1] === "unassign" && method === "POST") pool.project_id = null
  else if (parts[1] === "copy" && method === "POST") {
    const key = keys.find((item) => item.id === pool.credential_id)
    if (!key) return json(route, { detail: "Not found" }, 404)
    return json(route, createPool(key, { ...pool, ...input }), 201)
  } else if (parts.length === 1 && method === "PATCH") {
    for (const field of ["label", "rate", "budget", "operations", "operation_limits"] as const) {
      if (input[field] !== undefined) Object.assign(pool, { [field]: input[field] })
    }
  } else if (parts.length === 1 && method === "DELETE") {
    pools.splice(pools.indexOf(pool), 1)
    revision += 1
    return route.fulfill({ status: 204, body: "" })
  } else return json(route, { detail: "Not found" }, 404)
  revision += 1
  return json(route, pool)
}

export async function installVaultRoutes(page: Page, bridge: Bridge): Promise<void> {
  await page.route((url) => url.pathname.startsWith("/api/v1/account/vault/"), (route) => {
    const parts = new URL(route.request().url()).pathname.slice("/api/v1/account/vault/".length).split("/")
    const resource = parts.shift()
    const method = route.request().method()
    if (resource === "projects" && method === "GET") {
      return json(route, bridge.projects().map((project) => ({
        ...project, available_providers: ["brave", "tavily", "parallel", "exa", "you", "serper"],
      })))
    }
    if (resource === "keys") return handleKeys(route, parts, method)
    if (resource === "pools") return handlePools(route, parts, method)
    return json(route, { detail: "Not found" }, 404)
  })
  await page.route((url) => /^\/api\/v1\/projects\/[^/]+\/(pools|provider-owner|routing\/order)(\/.*)?$/.test(url.pathname), (route) => {
    const parts = new URL(route.request().url()).pathname.split("/")
    const project = parts[4]
    const resource = parts[5]
    const method = route.request().method()
    if (!bridge.access(project)) return json(route, { detail: "Not found" }, 404)
    if (resource === "provider-owner") {
      if (method === "GET") return json(route, vaultOwner(project, bridge.owner(project)))
      if (method === "POST") {
        const target = bridge.member(project, String(body(route).user_id))
        if (!target || !target.activeAdmin) return json(route, { detail: "The new provider owner must be an active project admin." }, 409)
        const owner = { user_id: target.user_id, email: target.email }
        const previous = vaultOwner(project, bridge.owner(project))
        if (previous?.user_id === owner.user_id) return json(route, { ...owner, unassigned_pools: [] })
        const unassigned = pools.filter((pool) => pool.project_id === project).map((pool) => ({ pool_id: pool.id, label: pool.label }))
        for (const pool of pools) if (pool.project_id === project) pool.project_id = null
        owners.set(project, owner)
        revision += 1
        return json(route, { ...owner, unassigned_pools: unassigned })
      }
    }
    if (resource === "pools") {
      if (method === "GET") return json(route, pools.filter((pool) => pool.project_id === project).map((pool) => projectPool(pool, bridge)))
      if (method === "POST") {
        const input = body(route)
        const key = typeof input.key_id === "string" ? keys.find((item) => item.id === input.key_id) :
          input.new_key && typeof input.new_key === "object" ? createKey(input.new_key as Body) : undefined
        if (!key || !input.pool || typeof input.pool !== "object") return json(route, { detail: "Invalid pool" }, 400)
        return json(route, projectPool(createPool(key, { ...(input.pool as Body), project_id: project }), bridge), 201)
      }
    }
    if (resource === "routing") {
      if (method === "GET" && parts.length === 7) return json(route, order(project))
      if (method === "PUT" && (parts[7] === "search" || parts[7] === "fetch")) {
        const input = body(route)
        const strategy = input.strategy
        if (strategy !== "free_first" && strategy !== "lowest_cost" && strategy !== "custom") return json(route, { detail: "Invalid strategy" }, 400)
        strategies.set(`${project}:${parts[7]}`, { strategy, order: Array.isArray(input.order) ? input.order as string[] : [] })
        revision += 1
        return json(route, order(project))
      }
    }
    return json(route, { detail: "Not found" }, 404)
  })
  await page.route((url) => /^\/api\/v1\/providers\/[^/]+\/limits\/keys(?:\/[^/]+\/sync)?$/.test(url.pathname), (route) => {
    const parts = new URL(route.request().url()).pathname.split("/")
    if (route.request().method() === "POST" && parts.at(-1) === "sync") return json(route, { status: "synced" })
    if (route.request().method() !== "GET") return json(route, { detail: "Not found" }, 404)
    return json(route, keys.filter((key) => key.provider_type === parts[4]).map((key) => ({
      key_id: key.id, label: key.label, owner_email: bridge.account().email, auth_mode: key.auth_mode,
      oauth_connected: key.auth_mode === "oauth" ? oauth.get(key.id) === "connected" : null,
      balance: balances.get(key.id) ?? null,
    })))
  })
}
