import { describe, expect, it } from "vitest"
import { traceEventLabel, traceEventOffsetText } from "./traceSpanPresentation"

describe("traceEventLabel", () => {
  it("names the recorded provider and request events in plain words", () => {
    expect(traceEventLabel("polyweb.provider.request")).toBe("Provider request")
    expect(traceEventLabel("polyweb.provider.response")).toBe("Provider response")
    expect(traceEventLabel("polyweb.response")).toBe("Response")
  })

  it("reads an unknown event as its last two segments", () => {
    expect(traceEventLabel("polyweb.cache.hit_miss")).toBe("Cache hit miss")
    expect(traceEventLabel("")).toBe("Event")
  })
})

describe("traceEventOffsetText", () => {
  it("states when the event happened relative to the trace start", () => {
    expect(traceEventOffsetText("2026-11-07T12:24:32.139Z", "2026-11-07T12:24:31.935Z")).toBe("+204 ms")
    expect(traceEventOffsetText("2026-11-07T12:24:33.435Z", "2026-11-07T12:24:31.935Z")).toBe(
      "+1,500 ms"
    )
  })

  it("keeps the raw timestamp when either time cannot be read", () => {
    expect(traceEventOffsetText("not-a-time", "2026-11-07T12:24:31.935Z")).toBe("not-a-time")
  })
})
