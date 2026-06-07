import { useEffect, useMemo, useState } from "react";
import { NavLink } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Film, Hash, Network } from "lucide-react";
import {
  api,
  type GraphData,
  type GraphFilters,
  type GraphItemBrief,
  type GraphNode,
} from "@/lib/api";
import { PlatformBadge } from "@/components/badges";

function MemberRow({ item }: { item: GraphItemBrief }) {
  return (
    <NavLink
      to={`/items/${item.item_id}`}
      className="group flex gap-3 rounded-md p-1.5 transition-colors hover:bg-accent"
    >
      <div className="aspect-video h-12 w-20 shrink-0 overflow-hidden rounded bg-muted">
        {item.thumbnail ? (
          <img src={item.thumbnail} alt="" className="h-full w-full object-cover" />
        ) : (
          <div className="flex h-full items-center justify-center text-muted-foreground">
            <Film className="h-4 w-4" />
          </div>
        )}
      </div>
      <div className="min-w-0 flex-1">
        <div className="mb-0.5">
          <PlatformBadge platform={item.platform} />
        </div>
        <p className="line-clamp-2 text-xs font-medium leading-snug">
          {item.title || item.source_url}
        </p>
      </div>
    </NavLink>
  );
}

export function ClusterPanel({
  node,
  graph,
  filters,
  onSelectCluster,
}: {
  node: GraphNode | null;
  graph: GraphData;
  filters?: GraphFilters;
  onSelectCluster: (id: number) => void;
}) {
  const [showAll, setShowAll] = useState(false);
  useEffect(() => setShowAll(false), [node?.id]);

  const neighbors = useMemo(() => {
    if (!node) return [];
    const ids = new Set<number>();
    for (const e of graph.edges) {
      if (e.source === node.id) ids.add(e.target);
      else if (e.target === node.id) ids.add(e.source);
    }
    return graph.nodes.filter((n) => ids.has(n.id));
  }, [node, graph]);

  const all = useQuery({
    queryKey: ["cluster-items", node?.id, filters],
    queryFn: () => api.getClusterItems(node!.id, 0, filters),
    enabled: showAll && node != null,
  });

  if (!node) {
    return (
      <div className="flex h-full flex-col items-center justify-center p-8 text-center text-sm text-muted-foreground">
        <Network className="mb-3 h-8 w-8 opacity-40" />
        Select a topic to see its articles and neighbors.
      </div>
    );
  }

  const members = showAll && all.data ? all.data : node.items;

  return (
    <div className="flex h-full flex-col overflow-hidden">
      <div className="border-b border-border p-4">
        <h2 className="text-lg font-semibold leading-tight">{node.label}</h2>
        <p className="mt-1 text-xs text-muted-foreground">
          {node.item_count} article{node.item_count === 1 ? "" : "s"} · {node.size} passages
        </p>
        {node.keywords.length > 0 && (
          <div className="mt-3 flex flex-wrap gap-1.5">
            {node.keywords.map((kw) => (
              <span
                key={kw}
                className="inline-flex items-center gap-1 rounded-full bg-accent px-2 py-0.5 text-xs text-accent-foreground"
              >
                <Hash className="h-3 w-3 opacity-60" />
                {kw}
              </span>
            ))}
          </div>
        )}
      </div>

      {neighbors.length > 0 && (
        <div className="border-b border-border p-4">
          <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Adjacent topics
          </h3>
          <div className="flex flex-wrap gap-1.5">
            {neighbors.map((n) => (
              <button
                key={n.id}
                onClick={() => onSelectCluster(n.id)}
                className="rounded-full border border-border px-2.5 py-1 text-xs transition-colors hover:border-primary hover:bg-accent"
              >
                {n.label}
              </button>
            ))}
          </div>
        </div>
      )}

      <div className="min-h-0 flex-1 overflow-y-auto p-3">
        <h3 className="mb-2 px-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          Articles
        </h3>
        <div className="space-y-0.5">
          {members.map((item) => (
            <MemberRow key={item.item_id} item={item} />
          ))}
        </div>
        {!showAll && node.item_count > node.items.length && (
          <button
            onClick={() => setShowAll(true)}
            className="mt-2 w-full rounded-md border border-border py-1.5 text-xs text-muted-foreground transition-colors hover:bg-accent"
          >
            Show all {node.item_count}
          </button>
        )}
        {showAll && all.isLoading && (
          <p className="py-2 text-center text-xs text-muted-foreground">Loading…</p>
        )}
      </div>
    </div>
  );
}
