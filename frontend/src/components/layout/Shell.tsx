import { Outlet } from "react-router";

import { Sidebar } from "./Sidebar";

export function Shell() {
  return (
    <div className="flex h-dvh bg-bg text-text">
      <Sidebar />
      <main className="min-w-0 flex-1 overflow-y-auto">
        <Outlet />
      </main>
    </div>
  );
}
