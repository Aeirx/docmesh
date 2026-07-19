import { lazy, Suspense } from "react";
import { createBrowserRouter, Navigate } from "react-router";

import { Shell } from "./components/layout/Shell";
import { AskPage } from "./features/ask/AskPage";
import { DocumentsPage } from "./features/documents/DocumentsPage";
import { SearchPage } from "./features/search/SearchPage";

// The graph view pulls in react-flow + d3-force + framer-motion — heavy, and
// only needed on /graph. Code-split it so it never lands in the initial bundle.
const GraphPage = lazy(() =>
  import("./features/graph/GraphPage").then((m) => ({ default: m.GraphPage })),
);

export const router = createBrowserRouter([
  {
    path: "/",
    element: <Shell />,
    children: [
      { index: true, element: <Navigate to="/documents" replace /> },
      { path: "documents", element: <DocumentsPage /> },
      { path: "search", element: <SearchPage /> },
      {
        path: "graph",
        element: (
          <Suspense fallback={<div className="dm-dotgrid h-full w-full" aria-busy="true" />}>
            <GraphPage />
          </Suspense>
        ),
      },
      { path: "ask", element: <AskPage /> },
      { path: "*", element: <Navigate to="/documents" replace /> },
    ],
  },
]);
