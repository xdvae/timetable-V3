import { Construction } from "lucide-react";

import { Page, Panel } from "@/components/layout/page.jsx";

/**
 * Foundation placeholder: proves the route + shell render with the right
 * title. Real page functionality ships in later phases — no fake UI here.
 */
export function PagePlaceholder({ title, subtitle, route }) {
  return (
    <Page title={title} subtitle={subtitle}>
      <Panel accent="brass" title="Coming in a later phase">
        <div className="flex items-start gap-3 text-sm text-muted-foreground">
          <Construction className="mt-0.5 size-4 shrink-0 text-brass-dark" aria-hidden="true" />
          <p>
            The <strong className="font-medium text-ink">{title}</strong> page will be built here
            {route ? (
              <>
                {" "}(route <code className="rounded bg-muted px-1 py-0.5 text-xs">{route}</code>)
              </>
            ) : null}
            . Routing, shell, and API foundations are already in place.
          </p>
        </div>
      </Panel>
    </Page>
  );
}
