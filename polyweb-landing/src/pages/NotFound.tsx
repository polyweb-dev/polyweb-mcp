import { PageLayout } from "./PageLayout"

export function NotFoundPage() {
  return (
    <PageLayout title="Page not found" intro="This address doesn't match any page.">
      <p className="page-body">
        <a href="#top">Back to Polyweb</a>
      </p>
    </PageLayout>
  )
}
