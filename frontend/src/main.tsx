import React, { Suspense, lazy } from "react";
import ReactDOM from "react-dom/client";
import { createBrowserRouter, RouterProvider } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Layout } from "@/components/Layout";
import { Library } from "@/pages/Library";
import { Search } from "@/pages/Search";
import { FolderView } from "@/pages/FolderView";
import { ItemDetail } from "@/pages/ItemDetail";
import { Annotations } from "@/pages/Annotations";
import { Queue } from "@/pages/Queue";
import { Subscriptions } from "@/pages/Subscriptions";
import { Stats } from "@/pages/Stats";
import { Settings } from "@/pages/Settings";
import { MIRROR } from "@/lib/mirror";
import "./index.css";

// The graph page pulls in the heavy force-graph/d3 bundle, so load it on demand.
const Graph = lazy(() =>
  import("@/pages/Graph").then((m) => ({ default: m.Graph })),
);

const queryClient = new QueryClient({
  defaultOptions: { queries: { refetchOnWindowFocus: false } },
});

// The public mirror only exposes read-only browsing + search; the live app
// additionally exposes the queue, subscriptions, stats, and settings.
const children = [
  { index: true, element: <Library /> },
  { path: "search", element: <Search /> },
  {
    path: "graph",
    element: (
      <Suspense fallback={<p className="text-muted-foreground">Loading graph…</p>}>
        <Graph />
      </Suspense>
    ),
  },
  { path: "folders/:id", element: <FolderView /> },
  { path: "items/:id", element: <ItemDetail /> },
  ...(MIRROR
    ? []
    : [
        { path: "annotations", element: <Annotations /> },
        { path: "queue", element: <Queue /> },
        { path: "subscriptions", element: <Subscriptions /> },
        { path: "stats", element: <Stats /> },
        { path: "settings", element: <Settings /> },
      ]),
];

const router = createBrowserRouter([
  {
    path: "/",
    element: <Layout />,
    children,
  },
]);

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  </React.StrictMode>,
);
