// Compatibility shim (Slice 4): canonical primitive lives in shared/ui.
// New code should import from @/shared/ui/table directly.
export {
  Table,
  TableHeader,
  TableBody,
  TableFooter,
  TableHead,
  TableRow,
  TableCell,
  TableCaption,
} from "@/shared/ui/table"
