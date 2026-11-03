import { RATE_ALGORITHMS } from "@/domains/providers"
import type { RateAlgorithm } from "@/domains/providers"
import { Button } from "@/shared/ui/button"
import type { ConstraintDraft } from "../model/poolDraft"
import { FIELD_CLASS, LABEL_CLASS } from "./formStyles"

const ALGORITHM_LABELS: Record<RateAlgorithm, string> = {
  fixed_window: "Fixed window",
  rolling_window: "Rolling window",
  token_bucket: "Token bucket",
}

interface PoolConstraintRowsProps {
  rows: readonly ConstraintDraft[]
  disabled: boolean
  onChange: (rows: ConstraintDraft[]) => void
}

/** Editable rate constraint rows of one pool, with "Add limit". */
export function PoolConstraintRows({ rows, disabled, onChange }: PoolConstraintRowsProps) {
  const update = (index: number, patch: Partial<ConstraintDraft>) =>
    onChange(rows.map((row, at) => (at === index ? { ...row, ...patch } : row)))

  return (
    <fieldset className="space-y-2">
      <legend className={LABEL_CLASS}>Rate limits</legend>
      {rows.map((row, index) => (
        <div key={index} className="grid grid-cols-[1fr_1fr_1fr_auto] items-end gap-2">
          <label className={LABEL_CLASS}>
            Algorithm
            <select
              value={row.algorithm}
              disabled={disabled}
              onChange={(event) =>
                update(index, {
                  algorithm: RATE_ALGORITHMS.find((value) => value === event.target.value) ?? row.algorithm,
                })
              }
              className={FIELD_CLASS}
            >
              {RATE_ALGORITHMS.map((algorithm) => (
                <option key={algorithm} value={algorithm}>{ALGORITHM_LABELS[algorithm]}</option>
              ))}
            </select>
          </label>
          <label className={LABEL_CLASS}>
            Window seconds
            <input type="number" min={1} value={row.windowSeconds} disabled={disabled} onChange={(event) => update(index, { windowSeconds: event.target.value })} className={FIELD_CLASS} />
          </label>
          <label className={LABEL_CLASS}>
            Limit
            <input type="number" min={0} value={row.limit} disabled={disabled} onChange={(event) => update(index, { limit: event.target.value })} className={FIELD_CLASS} />
          </label>
          <Button type="button" size="sm" variant="ghost" disabled={disabled} onClick={() => onChange(rows.filter((_, at) => at !== index))}>
            Remove limit
          </Button>
        </div>
      ))}
      <Button
        type="button"
        size="sm"
        variant="outline"
        disabled={disabled}
        onClick={() => onChange([...rows, { algorithm: "token_bucket", windowSeconds: "1", limit: "10" }])}
      >
        Add limit
      </Button>
    </fieldset>
  )
}
