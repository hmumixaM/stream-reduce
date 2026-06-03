import { useState } from "react";
import { NavLink, Outlet } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  LayoutGrid,
  ListChecks,
  Rss,
  BarChart3,
  Settings as SettingsIcon,
  Plus,
  Moon,
  Sun,
} from "lucide-react";
import { api } from "@/lib/api";
import { Button, Card, Spinner } from "@/components/ui";
import { cn } from "@/lib/utils";

const NAV = [
  { to: "/", label: "Library", icon: LayoutGrid, end: true },
  { to: "/queue", label: "Queue", icon: ListChecks },
  { to: "/subscriptions", label: "Subscriptions", icon: Rss },
  { to: "/stats", label: "Stats", icon: BarChart3 },
  { to: "/settings", label: "Settings", icon: SettingsIcon },
];

function AddDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [text, setText] = useState("");
  const qc = useQueryClient();
  const urls = text.split(/[\s,]+/).map((u) => u.trim()).filter(Boolean);
  const mutation = useMutation({
    mutationFn: (list: string[]) => api.addItems(list),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["items"] });
      qc.invalidateQueries({ queryKey: ["queue"] });
      setText("");
      onClose();
    },
  });
  if (!open) return null;
  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center bg-black/50 p-4 pt-32"
      onClick={onClose}
    >
      <Card className="w-full max-w-lg p-5" onClick={(e) => e.stopPropagation()}>
        <h2 className="mb-1 text-lg font-semibold">Add content</h2>
        <p className="mb-4 text-sm text-muted-foreground">
          Paste one or more YouTube, Bilibili, Apple Podcast, 小宇宙, or direct
          media URLs — one per line. Tracking params are stripped automatically.
        </p>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (urls.length) mutation.mutate(urls);
          }}
          className="space-y-3"
        >
          <textarea
            autoFocus
            rows={5}
            placeholder={"https://www.youtube.com/watch?v=...\nhttps://www.bilibili.com/video/BV..."}
            value={text}
            onChange={(e) => setText(e.target.value)}
            className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          />
          <div className="flex items-center justify-between">
            <span className="text-xs text-muted-foreground">
              {urls.length} URL{urls.length === 1 ? "" : "s"}
            </span>
            <Button type="submit" disabled={mutation.isPending || urls.length === 0}>
              {mutation.isPending ? <Spinner /> : `Add ${urls.length || ""}`.trim()}
            </Button>
          </div>
        </form>
        {mutation.isError && (
          <p className="mt-2 text-sm text-red-400">{String(mutation.error)}</p>
        )}
      </Card>
    </div>
  );
}

export function Layout() {
  const [addOpen, setAddOpen] = useState(false);
  const [dark, setDark] = useState(
    () => document.documentElement.classList.contains("dark"),
  );
  const queue = useQuery({ queryKey: ["queue"], queryFn: api.listQueue, refetchInterval: 4000 });
  const active = (queue.data ?? []).filter((i) => i.status !== "error").length;

  const toggleTheme = () => {
    document.documentElement.classList.toggle("dark");
    setDark(document.documentElement.classList.contains("dark"));
  };

  return (
    <div className="flex min-h-screen">
      <aside className="flex w-60 flex-col border-r border-border bg-card/40 p-4">
        <div className="mb-6 flex items-center gap-2 px-2">
          <div className="flex h-8 w-8 items-center justify-center rounded-md bg-primary text-primary-foreground font-bold">
            S
          </div>
          <span className="text-lg font-semibold">stream-reduce</span>
        </div>
        <Button className="mb-4 w-full" onClick={() => setAddOpen(true)}>
          <Plus className="h-4 w-4" /> Add content
        </Button>
        <nav className="flex flex-1 flex-col gap-1">
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) =>
                cn(
                  "flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors",
                  isActive
                    ? "bg-accent text-accent-foreground"
                    : "text-muted-foreground hover:bg-accent/60 hover:text-foreground",
                )
              }
            >
              <item.icon className="h-4 w-4" />
              {item.label}
              {item.to === "/queue" && active > 0 && (
                <span className="ml-auto rounded-full bg-primary px-1.5 text-xs text-primary-foreground">
                  {active}
                </span>
              )}
            </NavLink>
          ))}
        </nav>
        <Button variant="ghost" size="sm" className="justify-start" onClick={toggleTheme}>
          {dark ? <Moon className="h-4 w-4" /> : <Sun className="h-4 w-4" />}
          {dark ? "Dark" : "Light"} mode
        </Button>
      </aside>
      <main className="flex-1 overflow-auto">
        <div className="mx-auto max-w-6xl p-6">
          <Outlet />
        </div>
      </main>
      <AddDialog open={addOpen} onClose={() => setAddOpen(false)} />
    </div>
  );
}
