import type { LucideIcon } from "lucide-react";

/** Styled placeholder for routes whose features land in later phases.
 *  Lives in its own file so App.tsx exports only the router (react-refresh
 *  is happiest when a module exports either components or values, not both). */
export function ComingSoon({
  icon: Icon,
  title,
  phase,
  blurb,
}: {
  icon: LucideIcon;
  title: string;
  phase: number;
  blurb: string;
}) {
  return (
    <div className="flex h-full items-center justify-center px-8">
      <div className="max-w-md text-center">
        <div className="mx-auto flex size-14 items-center justify-center rounded-lg border border-border bg-surface">
          <Icon className="size-6 text-accent" strokeWidth={1.75} />
        </div>
        <h1 className="mt-6 text-xl font-bold tracking-tight">{title}</h1>
        <p className="mt-2 text-sm leading-relaxed text-muted">{blurb}</p>
        <span className="mt-6 inline-flex items-center gap-2 rounded-full border border-border bg-surface px-3 py-1 text-xs font-medium text-muted">
          <span className="size-1.5 rounded-full bg-accent" />
          Coming in Phase {phase}
        </span>
      </div>
    </div>
  );
}
