import { Link } from "react-router";

import { Separator } from "@/components/ui/separator.jsx";
import { cn } from "@/lib/utils";

/**
 * Reusable content layout: breadcrumbs, title, subtitle, header actions,
 * then a consistently spaced, width-capped content area.
 */
export function Page({ title, subtitle, actions, breadcrumbs, children, className }) {
  return (
    <div className={cn("mx-auto w-full max-w-[1400px] p-4 lg:p-7", className)}>
      {breadcrumbs && breadcrumbs.length > 0 ? (
        <nav aria-label="Breadcrumb" className="mb-2">
          <ol className="flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
            {breadcrumbs.map((crumb, index) => {
              const isLast = index === breadcrumbs.length - 1;
              return (
                <li key={crumb.label} className="flex items-center gap-1.5">
                  {index > 0 ? <span aria-hidden="true">/</span> : null}
                  {crumb.to && !isLast ? (
                    <Link to={crumb.to} className="text-steel underline-offset-4 outline-none hover:underline focus-visible:ring-2 focus-visible:ring-ring">
                      {crumb.label}
                    </Link>
                  ) : (
                    <span aria-current={isLast ? "page" : undefined}>{crumb.label}</span>
                  )}
                </li>
              );
            })}
          </ol>
        </nav>
      ) : null}

      <div className="mb-5 flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h1 className="text-2xl font-semibold text-ink">{title}</h1>
          {subtitle ? <p className="mt-1 text-sm text-muted-foreground">{subtitle}</p> : null}
        </div>
        {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
      </div>

      {children}
    </div>
  );
}

/** Card-like content panel with the institutional left-rule accent. */
export function Panel({ title, description, actions, accent = "ink", children, className }) {
  const accents = {
    ink: "border-l-ink",
    brass: "border-l-brass",
    steel: "border-l-steel",
    sage: "border-l-sage",
  };
  return (
    <section className={cn("rounded-lg border border-line border-l-[3px] bg-panel p-5", accents[accent], className)}>
      {title || description || actions ? (
        <div className="mb-4">
          <div className="flex flex-wrap items-start justify-between gap-2">
            {title ? <h2 className="text-base font-semibold text-ink">{title}</h2> : null}
            {actions}
          </div>
          {description ? <p className="mt-1 text-sm text-muted-foreground">{description}</p> : null}
          <Separator className="mt-3" />
        </div>
      ) : null}
      {children}
    </section>
  );
}
