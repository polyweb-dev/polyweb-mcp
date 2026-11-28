/**
 * Per-test resource metrics (layer 2) for Vitest, off unless
 * POLYWEB_TEST_METRICS=1. Each test file appends one JSON line per test to
 * `${POLYWEB_TEST_METRICS_DIR:-../test_reports/metrics}/vitest-<thread>.jsonl`.
 *
 * Vitest runs test files in worker threads that share one process, so only
 * per-thread numbers are meaningful: wall time, this thread's CPU time
 * (`process.threadCpuUsage`, Node 23.9+), and this thread's V8 heap. Process
 * RSS is recorded too but covers every thread. Each probe costs microseconds.
 */
import { appendFileSync, mkdirSync } from "node:fs"
import path from "node:path"
import { getHeapStatistics } from "node:v8"
import { threadId } from "node:worker_threads"
import { afterAll, afterEach, beforeEach } from "vitest"

const enabled = !["", "0", "false", "no"].includes(process.env.POLYWEB_TEST_METRICS ?? "")

type CpuUsage = { user: number; system: number }
type Start = { wall: number; cpu: CpuUsage; heap: number }

const cpuUsage = (): CpuUsage =>
  typeof process.threadCpuUsage === "function" ? process.threadCpuUsage() : process.cpuUsage()
const mib = (bytes: number) => Math.round((bytes / 1048576) * 10) / 10

if (enabled) {
  const directory = path.resolve(
    process.env.POLYWEB_TEST_METRICS_DIR ?? path.join(process.cwd(), "..", "test_reports", "metrics"),
  )
  const rows: string[] = []
  let start: Start | undefined

  beforeEach(() => {
    start = { wall: performance.now(), cpu: cpuUsage(), heap: getHeapStatistics().used_heap_size }
  })

  afterEach((context) => {
    if (!start) return
    const wallMs = performance.now() - start.wall
    const cpu = cpuUsage()
    const cpuMs = (cpu.user - start.cpu.user + cpu.system - start.cpu.system) / 1000
    const heap = getHeapStatistics().used_heap_size
    rows.push(
      JSON.stringify({
        schema: "polyweb.test-metrics/1",
        runner: "vitest",
        file: path.relative(process.cwd(), context.task.file.filepath),
        name: context.task.fullName ?? context.task.name,
        wall_s: Math.round(wallMs) / 1000,
        cpu_s: Math.round(cpuMs) / 1000,
        cpu_ratio: Math.round((cpuMs / Math.max(wallMs, 1e-6)) * 1000) / 1000,
        cpu_scope: typeof process.threadCpuUsage === "function" ? "thread" : "process",
        heap_mib: mib(heap),
        heap_delta_mib: mib(heap - start.heap),
        process_rss_mib: mib(process.memoryUsage.rss()),
      }),
    )
    start = undefined
  })

  afterAll(() => {
    if (rows.length === 0) return
    mkdirSync(directory, { recursive: true })
    appendFileSync(path.join(directory, `vitest-${process.pid}-${threadId}.jsonl`), rows.join("\n") + "\n")
    rows.length = 0
  })
}
