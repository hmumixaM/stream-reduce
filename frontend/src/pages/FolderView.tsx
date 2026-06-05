import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { ArrowLeft, Film, Pencil, Plus, Trash2 } from "lucide-react";
import { api, type Item } from "@/lib/api";
import { MIRROR } from "@/lib/mirror";
import { Button, Card, Input } from "@/components/ui";
import { PlatformBadge } from "@/components/badges";
import { ItemCard, type ItemCardActions } from "@/components/ItemCard";

const PAGE_SIZE = 60;

export function FolderView() {
  const { id } = useParams();
  const folderId = Number(id);
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [adding, setAdding] = useState(false);

  const groups = useQuery({ queryKey: ["groups"], queryFn: () => api.listGroups() });
  const folder = (groups.data ?? []).find((g) => g.id === folderId);

  const items = useInfiniteQuery({
    queryKey: ["items", { group_id: folderId }],
    queryFn: ({ pageParam }) =>
      api.listItems({
        group_id: folderId,
        sort: "position",
        order: "asc",
        limit: PAGE_SIZE,
        offset: pageParam,
      }),
    initialPageParam: 0,
    getNextPageParam: (lastPage, allPages) =>
      lastPage.length === PAGE_SIZE ? allPages.length * PAGE_SIZE : undefined,
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
  const rename = useMutation({
    mutationFn: (title: string) => api.renameGroup(folderId, title),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["groups"] }),
  });
  const remove = useMutation({
    mutationFn: () => api.deleteGroup(folderId),
    onSuccess: () => {
      invalidate();
      navigate("/");
    },
  });

  const actions: ItemCardActions = {
    onFavorite: favorite.mutate,
    onArchive: archive.mutate,
    groups: groups.data ?? [],
    onMove: (itemId, gid) => move.mutate({ id: itemId, gid }),
    onCreateFolderAndMove: (itemId, title) => createAndMove.mutate({ id: itemId, title }),
  };

  const members = items.data?.pages.flat() ?? [];

  const handleRename = () => {
    const title = window.prompt("Rename folder", folder?.title || "")?.trim();
    if (title) rename.mutate(title);
  };
  const handleDelete = () => {
    if (window.confirm("Delete this folder? Items will be kept and detached.")) {
      remove.mutate();
    }
  };

  return (
    <div>
      <Link
        to="/"
        className="mb-4 inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="h-4 w-4" /> Library
      </Link>

      <div className="mb-6 flex items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <h1 className="text-2xl font-semibold">{folder?.title || "Folder"}</h1>
          {folder?.source_url && <PlatformBadge platform={folder.platform} />}
          <span className="text-sm text-muted-foreground">
            {folder?.item_count ?? members.length} items
          </span>
        </div>
        {!MIRROR && (
          <div className="flex items-center gap-2">
            <Button variant="outline" size="sm" onClick={() => setAdding(true)}>
              <Plus className="h-4 w-4" /> Add items
            </Button>
            <Button variant="outline" size="sm" onClick={handleRename}>
              <Pencil className="h-4 w-4" /> Rename
            </Button>
            <Button variant="danger" size="sm" onClick={handleDelete}>
              <Trash2 className="h-4 w-4" /> Delete
            </Button>
          </div>
        )}
      </div>

      {items.isLoading ? (
        <p className="text-muted-foreground">Loading...</p>
      ) : members.length > 0 ? (
        <>
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
            {members.map((item) => (
              <ItemCard key={item.id} item={item} {...actions} />
            ))}
          </div>
          {items.hasNextPage && (
            <div className="mt-6 flex justify-center">
              <Button
                variant="outline"
                onClick={() => items.fetchNextPage()}
                disabled={items.isFetchingNextPage}
              >
                {items.isFetchingNextPage ? "Loading…" : "Load more"}
              </Button>
            </div>
          )}
        </>
      ) : (
        <Card className="p-10 text-center text-muted-foreground">
          {MIRROR ? "This folder is empty." : 'This folder is empty. Click "Add items" to fill it.'}
        </Card>
      )}

      {adding && (
        <AddToFolderDialog
          folderId={folderId}
          onClose={() => setAdding(false)}
          onAdd={(itemId) => move.mutate({ id: itemId, gid: folderId })}
        />
      )}
    </div>
  );
}

function AddToFolderDialog({
  folderId,
  onClose,
  onAdd,
}: {
  folderId: number;
  onClose: () => void;
  onAdd: (itemId: number) => void;
}) {
  const [q, setQ] = useState("");
  const candidates = useQuery({
    queryKey: ["items", { addPicker: true, q }],
    queryFn: () => api.listItems({ q: q || undefined, limit: 200 }),
  });
  const list = (candidates.data ?? []).filter((i) => i.group_id !== folderId);

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center bg-black/50 p-4 pt-24"
      onClick={onClose}
    >
      <Card className="flex max-h-[70vh] w-full max-w-lg flex-col p-5" onClick={(e) => e.stopPropagation()}>
        <h2 className="mb-1 text-lg font-semibold">Add items to folder</h2>
        <p className="mb-3 text-sm text-muted-foreground">
          Click an item to move it into this folder.
        </p>
        <Input
          autoFocus
          placeholder="Search titles..."
          value={q}
          onChange={(e) => setQ(e.target.value)}
          className="mb-3"
        />
        <div className="-mx-2 flex-1 overflow-y-auto">
          {list.length === 0 ? (
            <p className="px-2 py-6 text-center text-sm text-muted-foreground">
              No matching items.
            </p>
          ) : (
            list.map((item) => (
              <PickerRow key={item.id} item={item} onAdd={() => onAdd(item.id)} />
            ))
          )}
        </div>
        <div className="mt-3 flex justify-end">
          <Button variant="outline" size="sm" onClick={onClose}>
            Done
          </Button>
        </div>
      </Card>
    </div>
  );
}

function PickerRow({ item, onAdd }: { item: Item; onAdd: () => void }) {
  const [added, setAdded] = useState(false);
  return (
    <button
      onClick={() => {
        onAdd();
        setAdded(true);
      }}
      disabled={added}
      className="flex w-full items-center gap-3 rounded-md px-2 py-2 text-left hover:bg-accent disabled:opacity-50"
    >
      <div className="h-10 w-16 shrink-0 overflow-hidden rounded bg-muted">
        {item.thumbnail ? (
          <img src={item.thumbnail} alt="" className="h-full w-full object-cover" />
        ) : (
          <div className="flex h-full items-center justify-center text-muted-foreground">
            <Film className="h-4 w-4" />
          </div>
        )}
      </div>
      <span className="min-w-0 flex-1 truncate text-sm">{item.title || item.source_url}</span>
      {added ? (
        <span className="shrink-0 text-xs text-muted-foreground">Added</span>
      ) : (
        <Plus className="h-4 w-4 shrink-0 text-primary" />
      )}
    </button>
  );
}
