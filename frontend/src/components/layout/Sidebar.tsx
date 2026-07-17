import clsx from "clsx";
import type { LucideIcon } from "lucide-react";
import { FileText, MessageCircleQuestion, Search, Waypoints } from "lucide-react";
import { NavLink } from "react-router";

const NAV_ITEMS: { to: string; label: string; icon: LucideIcon }[] = [
  { to: "/documents", label: "Documents", icon: FileText },
  { to: "/search", label: "Search", icon: Search },
  { to: "/graph", label: "Graph", icon: Waypoints },
  { to: "/ask", label: "Ask", icon: MessageCircleQuestion },
];

function Logo() {
  return (
    <div className="flex items-center gap-2.5 px-3">
      {/* Mark: three linked nodes — the "mesh" */}
      <svg viewBox="0 0 32 32" className="size-7 shrink-0" aria-hidden="true">
        <rect width="32" height="32" rx="7" className="fill-accent/15" />
        <path
          d="M10 21 L16 11 L22 21 Z"
          className="stroke-accent"
          fill="none"
          strokeWidth="2"
          strokeLinejoin="round"
        />
        <circle cx="16" cy="11" r="3" className="fill-bg stroke-accent" strokeWidth="2" />
        <circle cx="10" cy="21" r="3" className="fill-bg stroke-accent" strokeWidth="2" />
        <circle cx="22" cy="21" r="3" className="fill-bg stroke-accent" strokeWidth="2" />
      </svg>
      <span className="text-[15px] font-bold tracking-tight">DocMesh</span>
    </div>
  );
}

export function Sidebar() {
  return (
    <aside className="flex w-60 shrink-0 flex-col border-r border-border bg-surface/50">
      <div className="pt-5 pb-6">
        <Logo />
      </div>

      <nav className="flex flex-1 flex-col gap-0.5 px-3" aria-label="Primary">
        {NAV_ITEMS.map(({ to, label, icon: Icon }) => (
          <NavLink
            key={to}
            to={to}
            className={({ isActive }) =>
              clsx(
                "group relative flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium",
                "transition-colors duration-150",
                isActive
                  ? "bg-accent/10 text-text"
                  : "text-muted hover:bg-surface-raised hover:text-text",
              )
            }
          >
            {({ isActive }) => (
              <>
                {/* Active indicator: a short accent bar hugging the left edge */}
                <span
                  className={clsx(
                    "absolute left-0 h-4 w-0.5 rounded-full bg-accent transition-opacity duration-150",
                    isActive ? "opacity-100" : "opacity-0",
                  )}
                />
                <Icon
                  className={clsx(
                    "size-[18px] transition-colors duration-150",
                    isActive ? "text-accent" : "text-muted group-hover:text-text",
                  )}
                  strokeWidth={1.75}
                />
                {label}
              </>
            )}
          </NavLink>
        ))}
      </nav>

      <div className="border-t border-border px-6 py-4">
        <p className="text-xs font-medium text-muted">
          v0.1.0 <span className="mx-1.5 text-border">·</span> Phase 2
        </p>
      </div>
    </aside>
  );
}
