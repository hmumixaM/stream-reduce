import { useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Folder, FolderPlus } from "lucide-react";
import { api, type Group } from "@/lib/api";
import { Button, Card, Input, Select } from "@/components/ui";
import { PlatformBadge } from "@/components/badges";
import { ItemCard, type ItemCardActions } from "@/components/ItemCard";

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
  const groups = useQuery({
    queryKey: ["groups"],
    queryFn: () => api.listGroups(),
    refetchInterval: 8000,
  });

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["items"] });
    qc.invalidateQueries({ queryKey: ["groups"] });
  };
  const favorite = useMutation({ mutationFn: api.toggleFavorite, onSuccess: invalidate });
  const archive = useMutation({ mutationFn: api.toggleArchive, onSuccess: invalidate });
  const move = useMutation({
    mutationFn: ({ id, gid }: { id: number; gid: number | null }) =>
      api.setItemGroup(id, gid),
    onSuccess: invalidate,
  });
  const createAndMove = useMutation({
    mutationFn: async ({ id, title }: { id: number; title: string }) => {
      const g = await api.createGroup(title);
      return api.setItemGroup(id, g.id);
    },
    onSuccess: invalidate,
  });
  const newFolder = useMutation({
    mutationFn: (title: string) => api.createGroup(title),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["groups"] }),
  });

  const actions: ItemCardActions = {
    onFavorite: favorite.mutate,
    onArchive: archive.mutate,
    groups: groups.data ?? [],
    onMove: (id, gid) => move.mutate({ id, gid }),
    onCreateFolderAndMove: (id, title) => createAndMove.mutate({ id, title }),
  };

  const all = items.data ?? [];
  // Folders are first-class navigation (always visible); the flat item grid
  // shows ungrouped items. A search/favorites/archived view flattens everything
  // so items can be found regardless of which folder they live in.
  const browsing = view === "all" && !q;
  const visibleItems = browsing
    ? all.filter((i) => i.group_id == null)
    : all;
  const folders = groups.data ?? [];

  const handleNewFolder = () => {
    const title = window.prompt("New folder name")?.trim();
    if (title) newFolder.mutate(title);
  };

  return (
    <div>
      <div className="mb-6 flex items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold">Library</h1>
          <p className="text-sm text-muted-foreground">
            {all.length} {view === "archived" ? "archived" : "summaries"}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" onClick={handleNewFolder}>
            <FolderPlus className="h-4 w-4" /> New folder
          </Button>
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

      {browsing && folders.length > 0 && (
        <div className="mb-8">
          <h2 className="mb-3 text-sm font-medium text-muted-foreground">Folders</h2>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
            {folders.map((g) => (
              <FolderTile key={g.id} group={g} />
            ))}
          </div>
        </div>
      )}

      {items.isLoading ? (
        <p className="text-muted-foreground">Loading...</p>
      ) : visibleItems.length > 0 ? (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
          {visibleItems.map((item) => (
            <ItemCard key={item.id} item={item} {...actions} />
          ))}
        </div>
      ) : folders.length > 0 && browsing ? (
        <Card className="p-10 text-center text-muted-foreground">
          All items are organized into folders. Open a folder to browse.
        </Card>
      ) : (
        <Card className="p-10 text-center text-muted-foreground">
          No summaries yet. Click "Add content" to get started.
        </Card>
      )}
    </div>
  );
}

function FolderTile({ group }: { group: Group }) {
  return (
    <Link to={`/folders/${group.id}`}>
      <Card className="flex h-full items-center gap-3 p-4 transition-colors hover:border-primary">
        <Folder className="h-8 w-8 shrink-0 text-primary" />
        <div className="min-w-0 flex-1">
          <div className="truncate font-medium">{group.title || "Folder"}</div>
          <div className="mt-1 flex items-center gap-2 text-xs text-muted-foreground">
            {group.source_url && <PlatformBadge platform={group.platform} />}
            <span>
              {group.item_count} item{group.item_count === 1 ? "" : "s"}
            </span>
          </div>
        </div>
      </Card>
    </Link>
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
