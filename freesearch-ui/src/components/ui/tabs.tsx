// Compatibility shim (Slice 4): canonical primitive lives in shared/ui.
// New code should import from @/shared/ui/tabs directly.
export {
  Tabs,
  TabsList,
  TabsTrigger,
  TabsContent,
  tabsListVariants,
} from "@/shared/ui/tabs"
