import React from "react";
import ReactDOM from "react-dom/client";
import { createBrowserRouter, RouterProvider } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Layout } from "@/components/Layout";
import { Library } from "@/pages/Library";
import { ItemDetail } from "@/pages/ItemDetail";
import { Queue } from "@/pages/Queue";
import { Subscriptions } from "@/pages/Subscriptions";
import { Stats } from "@/pages/Stats";
import { Settings } from "@/pages/Settings";
import "./index.css";

const queryClient = new QueryClient({
  defaultOptions: { queries: { refetchOnWindowFocus: false } },
});

const router = createBrowserRouter([
  {
    path: "/",
    element: <Layout />,
    children: [
      { index: true, element: <Library /> },
      { path: "items/:id", element: <ItemDetail /> },
      { path: "queue", element: <Queue /> },
      { path: "subscriptions", element: <Subscriptions /> },
      { path: "stats", element: <Stats /> },
      { path: "settings", element: <Settings /> },
    ],
  },
]);

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  </React.StrictMode>,
);
