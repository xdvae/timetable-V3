import { Link } from "react-router";

import { Page } from "@/components/layout/page.jsx";
import { Button } from "@/components/ui/button.jsx";

export function NotFoundPage() {
  return (
    <Page title="Page not found" subtitle="The address you opened doesn't match any UniSchedule page.">
      <Button asChild variant="outline">
        <Link to="/">Back to dashboard</Link>
      </Button>
    </Page>
  );
}
