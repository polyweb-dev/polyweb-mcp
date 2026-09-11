import { ComposerShell } from "@/components/common/ComposerShell"
import { useSimulatorController } from "../model/useSimulatorController"
import { SimulatorFooter } from "./SimulatorFooter"
import { SimulatorInputRow } from "./SimulatorInputRow"
import { SimulatorPipeline } from "./SimulatorPipeline"

/**
 * Route simulator: resolves a hypothetical request through the current
 * strategy and renders the ingress → primary → fallback pipeline.
 */
export function RouteSimulator() {
  const {
    operation,
    requestInput,
    hasSimulated,
    eligible,
    runOp,
    runPrimary,
    runFallbacks,
    failoverEnabled,
    routingPreset,
    setRequestInput,
    handleOperationChange,
    handleSimulate,
  } = useSimulatorController()

  return (
    <section className="flex flex-1 flex-col space-y-5 w-full max-w-none">
      <p className="text-[12px] text-[var(--muted)]">
        Remaining percentages are comparable; details keep each provider&apos;s native unit.
      </p>
      <div
        data-testid="simulator-layout"
        data-state={hasSimulated ? "docked" : "hero"}
        className={"transition-all duration-300 ease-out motion-reduce:transition-none " + (hasSimulated
          ? "top-docked"
          : "w-full mx-auto flex flex-1 min-h-[55vh] max-w-3xl flex-col justify-center")}
      >
        <ComposerShell
          testIdPrefix="simulator"
          inputRow={
            <SimulatorInputRow
              value={requestInput}
              operation={operation}
              onChange={setRequestInput}
              onSimulate={handleSimulate}
            />
          }
          footer={
            <SimulatorFooter
              operation={operation}
              onOperationChange={handleOperationChange}
            />
          }
        />
      </div>

      {eligible.length === 0 ? (
        <div className="p-2.5 rounded bg-[var(--surface)] border border-[var(--border-subtle)] text-[13px] text-[var(--muted)]">
          No eligible providers for this operation — enable global routing or a provider
          operation in settings.
        </div>
      ) : hasSimulated ? (
        <SimulatorPipeline
          operation={runOp}
          preset={routingPreset}
          primary={runPrimary}
          fallbacks={runFallbacks}
          failoverEnabled={failoverEnabled}
        />
      ) : null}
    </section>
  )
}
