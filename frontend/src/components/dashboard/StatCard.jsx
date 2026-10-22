import { Link } from "react-router";

import { cn } from "@/lib/utils";

/**
 * Dashboard summary tile. Renders as a link when `to` is provided,
 * otherwise as a static block. Value + label always pair text with the
 * number (never color alone).
 */
export function StatCard({ label, value, icon: Icon, to, className }) {
  const inner = (
    <>
      <div className="flex items-center justify-between gap-2">
        <span className="font-display text-[2rem] leading-none font-semibold text-ink tabular-nums">
          {value}
        </span>
        {Icon ? <Icon className="size-5 shrink-0 text-muted-foreground" aria-hidden="true" /> : null}
      </div>
      <p className="mt-2 text-[0.78rem] text-muted-foreground">{label}</p>
    </>
  );
  const classes = cn(
    "rounded-lg border border-line bg-panel p-4",
    to && "transition-colors outline-none hover:border-brass focus-visible:ring-2 focus-visible:ring-ring",
    className
  );
  if (to) {
    return (
      <Link to={to} className={classes} aria-label={`${label}: ${value}`}>
        {inner}
      </Link>
    );
  }
  return <div className={classes}>{inner}</div>;
}
