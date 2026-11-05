import { Popover as PopoverPrimitive } from "@base-ui/react/popover"
import { cn } from "cn"

/**
 * Popover shell of the current theme.
 *
 * The primitive supplies the trigger wiring, the Escape key, the outside press,
 * and the focus return. The trigger carries `aria-haspopup`, `aria-expanded`,
 * and `aria-controls`. Only the shown surface comes from this file.
 *
 * The caller mounts the content only while the popover is open, so a closed
 * popover leaves no element behind and the focus returns to the trigger.
 */

function Popover({ ...props }: PopoverPrimitive.Root.Props) {
  return <PopoverPrimitive.Root data-slot="popover" {...props} />
}

function PopoverTrigger({ ...props }: PopoverPrimitive.Trigger.Props) {
  return <PopoverPrimitive.Trigger data-slot="popover-trigger" {...props} />
}

function PopoverTitle({ ...props }: PopoverPrimitive.Title.Props) {
  return <PopoverPrimitive.Title data-slot="popover-title" {...props} />
}

function PopoverContent({
  className,
  side = "bottom",
  align = "end",
  sideOffset = 6,
  alignOffset = 0,
  children,
  ...props
}: PopoverPrimitive.Popup.Props &
  Pick<
    PopoverPrimitive.Positioner.Props,
    "align" | "alignOffset" | "side" | "sideOffset"
  >) {
  return (
    <PopoverPrimitive.Portal>
      <PopoverPrimitive.Positioner
        align={align}
        alignOffset={alignOffset}
        side={side}
        sideOffset={sideOffset}
        collisionPadding={8}
        className="isolate z-50"
      >
        <PopoverPrimitive.Popup
          data-slot="popover-content"
          className={cn(
            "z-50 w-80 origin-(--transform-origin) rounded-lg p-4 text-xs/relaxed shadow-xl outline-none data-open:animate-in data-open:fade-in-0 data-open:zoom-in-95",
            className
          )}
          style={{
            background: "var(--elevated)",
            border: "1px solid var(--border-subtle)",
            color: "var(--text)",
          }}
          {...props}
        >
          {children}
        </PopoverPrimitive.Popup>
      </PopoverPrimitive.Positioner>
    </PopoverPrimitive.Portal>
  )
}

export { Popover, PopoverTrigger, PopoverTitle, PopoverContent }
