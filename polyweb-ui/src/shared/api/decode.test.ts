import { describe, expect, it } from "vitest"
import { asRecord, decodeList, decodeOne, readEnum, readFlag, readInt, readMembers, readString } from "./decode"

describe("decode helpers", () => {
  it("read only well-typed fields", () => {
    const record = { s: "x", n: 2, f: 1.5, t: true, e: "b", list: ["b", "z", "a"] }
    expect(asRecord([])).toBeNull()
    expect(readString(record, "s")).toBe("x")
    expect(readString(record, "n")).toBeNull()
    expect(readInt(record, "n")).toBe(2)
    expect(readInt(record, "f")).toBeNull()
    expect(readFlag(record, "t")).toBe(true)
    expect(readFlag(record, "s")).toBe(false)
    expect(readEnum(record, "e", ["a", "b"])).toBe("b")
    expect(readEnum(record, "s", ["a", "b"])).toBeNull()
    expect(readMembers(record, "list", ["a", "b"])).toEqual(["a", "b"])
  })

  it("decode lists and single objects", () => {
    const decode = (value: unknown) => (typeof value === "number" ? value : null)
    expect(decodeList([1, "x", 2], decode, "numbers")).toEqual([1, 2])
    expect(() => decodeList({}, decode, "numbers")).toThrow("numbers is not a list")
    expect(decodeOne(3, decode, "number")).toBe(3)
    expect(() => decodeOne("x", decode, "number")).toThrow()
  })
})
