import { Given, When } from "./fixtures"
import { projectStubId } from "./projectStub"
import { activateProviderConfigStub } from "./providerConfigStub"
import { watchBrowserTraffic } from "./providerConfigUi"

const PAGE_SEGMENTS: Record<string, string> = { Providers: "providers", Settings: "settings" }

Given("the provider configuration is stubbed", async ({ page }) => {
  activateProviderConfigStub()
  watchBrowserTraffic(page)
})

When("I open the {word} page of project {word}", async ({ page }, pageName: string, projectName: string) => {
  const segment = PAGE_SEGMENTS[pageName]
  if (segment === undefined) throw new Error(`unknown project page ${pageName}`)
  await page.goto(`/p/${projectStubId(projectName)}/${segment}`)
})
