import { useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Network, RefreshCw, Search as SearchIcon, X } from "lucide-react";
import { api, type GraphFilters } from "@/lib/api";
import { MIRROR } from "@/lib/mirror";
import { Button, Card, Input, Spinner } from "@/components/ui";
import { GraphCanvas, type GraphCanvasHandle } from "@/components/GraphCanvas";
import { ClusterPanel } from "@/components/ClusterPanel";
import { timeAgo } from "@/lib/utils";

const PLATFORMS = ["youtube", "bilibili", "apple_podcast", "xiaoyuzhou", "rss"];

function FilterChip({
  label,
  active,
  onClick,
}: {
  label: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className={`rounded-full border px-3 py-1 text-xs font-medium capitalize transition-colors ${
        active
          ? "border-primary bg-primary text-primary-foreground"
          : "border-border text-muted-foreground hover:bg-accent"
      }`}
    >
      {label.replace("_", " ")}
    </button>
  );
}

export function Graph() {
  const [params, setParams] = useSearchParams();
  const canvasRef = useRef<GraphCanvasHandle>(null);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [topicQuery, setTopicQuery] = useState("");

  const favorite = params.get("favorite") === "1";
  const archived = params.get("archived") === "1";
  const platform = params.get("platform") ?? "";
  const folders = (params.get("folders") ?? "")
    .split(",")
    .map((s) => Number(s))
    .filter((n) => Number.isFinite(n) && n > 0);
  const focus = params.get("focus");

  // In the mirror the graph is unified; filters are not exposed.
  const filters: GraphFilters | undefined = MIRROR
    ? undefined
    : { favorite, archived, platform: platform || undefined, folders };

  const setParam = (key: string, value: string | null) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    setParams(next, { replace: true });
  };

  const toggleFolder = (id: number) => {
    const set = new Set(folders);
    if (set.has(id)) set.delete(id);
    else set.add(id);
    setParam("folders", set.size ? [...set].join(",") : null);
  };

  const graph = useQuery({
    queryKey: ["graph", { favorite, archived, platform, folders: folders.join(",") }],
    queryFn: () => api.getGraph(filters),
  });
  const groups = useQuery({
    queryKey: ["groups"],
    queryFn: () => api.listGroups(),
    enabled: !MIRROR,
  });
  const rebuild = useMutation({ mutationFn: () => api.rebuildGraph() });

  const data = graph.data;
  const selectedNode = useMemo(
    () => data?.nodes.find((n) => n.id === selectedId) ?? null,
    [data, selectedId],
  );

  // Resolve a ?focus=<itemId> deep link into a centered cluster, once.
  const focusedRef = useRef<string | null>(null);
  useEffect(() => {
    if (!focus || !data || focusedRef.current === focus) return;
    focusedRef.current = focus;
    api.getItemCluster(Number(focus)).then((clusterId) => {
      if (clusterId != null) {
        setSelectedId(clusterId);
        setTimeout(() => canvasRef.current?.focusCluster(clusterId), 800);
      }
    });
  }, [focus, data]);

  const selectCluster = (id: number) => {
    setSelectedId(id);
    canvasRef.current?.focusCluster(id);
  };

  const runTopicSearch = (e: React.FormEvent) => {
    e.preventDefault();
    const q = topicQuery.trim().toLowerCase();
    if (!q || !data) return;
    const match =
      data.nodes.find((n) => n.label.toLowerCase().includes(q)) ??
      data.nodes.find((n) => n.keywords.some((k) => k.toLowerCase().includes(q)));
    if (match) selectCluster(match.id);
  };

  return (
    <div className="flex h-[calc(100vh-7rem)] flex-col md:h-[calc(100vh-3rem)]">
      <div className="mb-3 flex flex-col gap-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="flex items-center gap-2 text-2xl font-semibold">
              <Network className="h-6 w-6 text-primary" /> Knowledge graph
            </h1>
            <p className="text-sm text-muted-foreground">
              {data
                ? `${data.nodes.length} topics`
                : "Topic clusters across your library"}
              {data?.built_at && ` · built ${timeAgo(data.built_at)}`}
            </p>
          </div>
          <div className="flex items-center gap-2">
            <form onSubmit={runTopicSearch} className="relative">
              <SearchIcon className="absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                placeholder="Jump to topic…"
                value={topicQuery}
                onChange={(e) => setTopicQuery(e.target.value)}
                className="w-44 pl-8"
              />
            </form>
            {!MIRROR && (
              <Button
                variant="outline"
                size="sm"
                onClick={() => rebuild.mutate()}
                disabled={rebuild.isPending}
                title="Rebuild the graph from the latest content"
              >
                <RefreshCw className={`h-4 w-4 ${rebuild.isPending ? "animate-spin" : ""}`} />
                <span className="hidden sm:inline">Rebuild</span>
              </Button>
            )}
          </div>
        </div>

        {!MIRROR && (
          <div className="flex flex-wrap items-center gap-2">
            <FilterChip label="★ Favorites" active={favorite} onClick={() => setParam("favorite", favorite ? null : "1")} />
            <FilterChip label="Include archived" active={archived} onClick={() => setParam("archived", archived ? null : "1")} />
            <span className="mx-1 h-4 w-px bg-border" />
            <FilterChip label="All platforms" active={!platform} onClick={() => setParam("platform", null)} />
            {PLATFORMS.map((p) => (
              <FilterChip
                key={p}
                label={p}
                active={platform === p}
                onClick={() => setParam("platform", platform === p ? null : p)}
              />
            ))}
            {(groups.data?.length ?? 0) > 0 && <span className="mx-1 h-4 w-px bg-border" />}
            {(groups.data ?? []).map((g) => (
              <FilterChip
                key={g.id}
                label={g.title || "Folder"}
                active={folders.includes(g.id)}
                onClick={() => toggleFolder(g.id)}
              />
            ))}
          </div>
        )}
      </div>

      <div className="relative flex min-h-0 flex-1 gap-4">
        <Card className="relative min-h-0 flex-1 overflow-hidden">
          {graph.isLoading ? (
            <div className="flex h-full items-center justify-center text-muted-foreground">
              <Spinner /> <span className="ml-2">Loading graph…</span>
            </div>
          ) : graph.isError ? (
            <div className="flex h-full items-center justify-center text-sm text-red-400">
              Failed to load the graph.
            </div>
          ) : data && data.nodes.length > 0 ? (
            <GraphCanvas
              ref={canvasRef}
              data={data}
              selectedId={selectedId}
              onSelect={selectCluster}
            />
          ) : (
            <div className="flex h-full flex-col items-center justify-center p-8 text-center text-sm text-muted-foreground">
              <Network className="mb-3 h-8 w-8 opacity-40" />
              No topics yet.
              {!MIRROR && " Process more content, then rebuild the graph."}
            </div>
          )}
        </Card>

        {/* Desktop side panel */}
        {data && (
          <Card className="hidden w-80 shrink-0 overflow-hidden md:block">
            <ClusterPanel
              node={selectedNode}
              graph={data}
              filters={filters}
              onSelectCluster={selectCluster}
            />
          </Card>
        )}

        {/* Mobile bottom drawer */}
        {data && selectedNode && (
          <div className="absolute inset-x-0 bottom-0 z-20 max-h-[70%] overflow-hidden rounded-t-xl border border-border bg-card shadow-lg md:hidden">
            <button
              onClick={() => setSelectedId(null)}
              className="absolute right-2 top-2 z-10 rounded-md p-1.5 text-muted-foreground hover:bg-accent"
            >
              <X className="h-4 w-4" />
            </button>
            <div className="max-h-[70vh] overflow-hidden">
              <ClusterPanel
                node={selectedNode}
                graph={data}
                filters={filters}
                onSelectCluster={selectCluster}
              />
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
