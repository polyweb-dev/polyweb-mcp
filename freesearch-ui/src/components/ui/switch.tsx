import { Switch as SwitchPrimitive } from "@base-ui/react/switch"
import { cn } from "cn"

function Switch({ className, ...props }: SwitchPrimitive.Root.Props) {
  return (
    <SwitchPrimitive.Root
      data-slot="switch"
      className={cn(
        "peer group/switch relative inline-flex h-5 w-9 shrink-0 items-center rounded-full border border-[var(--border-subtle)] bg-transparent p-0.5 transition-all duration-200 ease-in-out outline-none motion-reduce:transition-none",
        // Invisible expanded hit target so the 36px track is comfortably tappable.
        "before:absolute before:-inset-2 before:content-['']",
        "focus-visible:border-[var(--signal)] focus-visible:ring-2 focus-visible:ring-[var(--signal)]/40",
        "data-checked:border-transparent data-checked:bg-[var(--signal)]",
        "data-disabled:cursor-not-allowed data-disabled:opacity-50",
        className
      )}
      {...props}
    >
      <SwitchPrimitive.Thumb
        data-slot="switch-thumb"
        className="pointer-events-none block h-4 w-4 rounded-full bg-[var(--text-strong)] shadow-sm transition-transform duration-200 ease-in-out motion-reduce:transition-none data-checked:translate-x-[14px] dark:data-checked:bg-white"
      />
    </SwitchPrimitive.Root>
  )
}

export { Switch }
