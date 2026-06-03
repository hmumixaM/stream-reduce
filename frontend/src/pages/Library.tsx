import { useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Clock, Coins, Film, Star, Archive, ArchiveRestore, Eye, ThumbsUp, CalendarDays } from "lucide-react";
import { api } from "@/lib/api";
import { Card, Input, Select } from "@/components/ui";
import { PlatformBadge, StatusBadge } from "@/components/badges";
import { formatCost, formatCount, formatDate, formatMs, timeAgo } from "@/lib/utils";

const PLATFORMS = ["youtube", "bilibili", "apple_podcast", "xiaoyuzhou", "rss"];
type View = "all" | "favorites" | "archived";

const SORTS: { value: string; label: string }[] = [
  { value: "added", label: "Recently added" },
  { value: "published", label: "Publish date" },
  { value: "views", label: "Most views" },
  { value: "likes", label: "Most likes" },
  { value: "duration", label: "Longest" },
];

export function Library() {
  const [q, setQ] = useState("");
  const [platform, setPlatform] = useState<string>("");
  const [view, setView] = useState<View>("all");
  const [sort, setSort] = useState<string>("added");
  const qc = useQueryClient();

  const params = {
    q: q || undefined,
    platform: platform || undefined,
    favorite: view === "favorites" ? true : undefined,
    archived: view === "archived" ? true : false,
    sort,
    order: "desc",
  };
  const items = useQuery({
    queryKey: ["items", { q, platform, view, sort }],
    queryFn: () => api.listItems(params),
    refetchInterval: 8000,
  });

  const invalidate = () => qc.invalidateQueries({ queryKey: ["items"] });
  const favorite = useMutation({ mutationFn: api.toggleFavorite, onSuccess: invalidate });
  const archive = useMutation({ mutationFn: api.toggleArchive, onSuccess: invalidate });

  return (
    <div>
      <div className="mb-6 flex items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold">Library</h1>
          <p className="text-sm text-muted-foreground">
            {items.data?.length ?? 0} {view === "archived" ? "archived" : "summaries"}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Select
            value={sort}
            onChange={(e) => setSort(e.target.value)}
            className="w-40"
            title="Sort by"
          >
            {SORTS.map((s) => (
              <option key={s.value} value={s.value}>
                {s.label}
              </option>
            ))}
          </Select>
          <Input
            placeholder="Search titles..."
            value={q}
            onChange={(e) => setQ(e.target.value)}
            className="max-w-xs"
          />
        </div>
      </div>

      <div className="mb-4 flex flex-wrap gap-2">
        <FilterChip label="All" active={view === "all"} onClick={() => setView("all")} />
        <FilterChip
          label="★ Favorites"
          active={view === "favorites"}
          onClick={() => setView("favorites")}
        />
        <FilterChip
          label="Archived"
          active={view === "archived"}
          onClick={() => setView("archived")}
        />
      </div>

      <div className="mb-5 flex flex-wrap gap-2">
        <FilterChip label="All" active={!platform} onClick={() => setPlatform("")} />
        {PLATFORMS.map((p) => (
          <FilterChip
            key={p}
            label={p}
            active={platform === p}
            onClick={() => setPlatform(platform === p ? "" : p)}
          />
        ))}
      </div>

      {items.isLoading ? (
        <p className="text-muted-foreground">Loading...</p>
      ) : items.data && items.data.length > 0 ? (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
          {items.data.map((item) => (
            <Link key={item.id} to={`/items/${item.id}`}>
              <Card className="group relative h-full overflow-hidden transition-colors hover:border-primary">
                <div className="absolute right-2 top-2 z-10 flex gap-1">
                  <CardAction
                    title={item.is_favorite ? "Unfavorite" : "Favorite"}
                    active={item.is_favorite}
                    onClick={() => favorite.mutate(item.id)}
                  >
                    <Star
                      className={`h-4 w-4 ${item.is_favorite ? "fill-amber-400 text-amber-400" : ""}`}
                    />
                  </CardAction>
                  <CardAction
                    title={item.is_archived ? "Unarchive" : "Archive"}
                    onClick={() => archive.mutate(item.id)}
                  >
                    {item.is_archived ? (
                      <ArchiveRestore className="h-4 w-4" />
                    ) : (
                      <Archive className="h-4 w-4" />
                    )}
                  </CardAction>
                </div>
                <div className="aspect-video w-full overflow-hidden bg-muted">
                  {item.thumbnail ? (
                    <img
                      src={item.thumbnail}
                      alt=""
                      className="h-full w-full object-cover transition-transform group-hover:scale-105"
                    />
                  ) : (
                    <div className="flex h-full items-center justify-center text-muted-foreground">
                      <Film className="h-8 w-8" />
                    </div>
                  )}
                </div>
                <div className="p-4">
                  <div className="mb-2 flex items-center gap-2">
                    <PlatformBadge platform={item.platform} />
                    <StatusBadge status={item.status} />
                  </div>
                  <h3 className="mb-2 line-clamp-2 font-medium leading-snug">
                    {item.title || item.source_url}
                  </h3>
                  <div className="flex flex-wrap items-center gap-3 text-xs text-muted-foreground">
                    {item.author && <span className="truncate">{item.author}</span>}
                    <span>added {timeAgo(item.created_at)}</span>
                  </div>
                  <div className="mt-2 flex flex-wrap items-center gap-3 text-xs text-muted-foreground">
                    {item.published_at && (
                      <span className="flex items-center gap-1">
                        <CalendarDays className="h-3 w-3" />
                        {formatDate(item.published_at)}
                      </span>
                    )}
                    {item.view_count != null && (
                      <span className="flex items-center gap-1" title="Views at crawl time">
                        <Eye className="h-3 w-3" />
                        {formatCount(item.view_count)}
                      </span>
                    )}
                    {item.like_count != null && (
                      <span className="flex items-center gap-1" title="Likes at crawl time">
                        <ThumbsUp className="h-3 w-3" />
                        {formatCount(item.like_count)}
                      </span>
                    )}
                  </div>
                  <div className="mt-2 flex items-center gap-4 text-xs text-muted-foreground">
                    <span className="flex items-center gap-1">
                      <Clock className="h-3 w-3" />
                      {formatMs(item.total_processing_ms)}
                    </span>
                    <span className="flex items-center gap-1">
                      <Coins className="h-3 w-3" />
                      {formatCost(item.total_cost_usd)}
                    </span>
                  </div>
                </div>
              </Card>
            </Link>
          ))}
        </div>
      ) : (
        <Card className="p-10 text-center text-muted-foreground">
          No summaries yet. Click "Add content" to get started.
        </Card>
      )}
    </div>
  );
}

function CardAction({
  title,
  active,
  onClick,
  children,
}: {
  title: string;
  active?: boolean;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <button
      title={title}
      onClick={(e) => {
        e.preventDefault();
        e.stopPropagation();
        onClick();
      }}
      className={`rounded-md border border-border p-1.5 backdrop-blur transition-colors ${
        active
          ? "bg-background/90 text-amber-400"
          : "bg-background/70 text-muted-foreground hover:bg-background hover:text-foreground"
      }`}
    >
      {children}
    </button>
  );
}

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
