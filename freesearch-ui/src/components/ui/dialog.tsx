// Compatibility shim (Slice 4): canonical primitive lives in shared/ui.
// New code should import from @/shared/ui/dialog directly.
export {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogOverlay,
  DialogPortal,
  DialogTitle,
  DialogTrigger,
} from "@/shared/ui/dialog"
