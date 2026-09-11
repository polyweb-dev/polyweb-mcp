// Compatibility shim (Slice 4): canonical primitive lives in shared/ui.
// New code should import from @/shared/ui/tooltip directly.
export {
  Tooltip,
  TooltipTrigger,
  TooltipContent,
  TooltipProvider,
} from "@/shared/ui/tooltip"
