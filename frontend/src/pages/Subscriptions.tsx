import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { RefreshCw, Trash2, Power } from "lucide-react";
import { api } from "@/lib/api";
import { Button, Card, Input, Spinner } from "@/components/ui";
import { PlatformBadge } from "@/components/badges";
import { timeAgo } from "@/lib/utils";

export function Subscriptions() {
  const qc = useQueryClient();
  const [feed, setFeed] = useState("");
  const [interval, setIntervalMin] = useState("60");

  const subs = useQuery({ queryKey: ["subs"], queryFn: api.listSubscriptions });
  const add = useMutation({
    mutationFn: () => api.addSubscription(feed.trim(), Number(interval) || 60),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["subs"] });
      setFeed("");
    },
  });
  const toggle = useMutation({
    mutationFn: (id: number) => api.toggleSubscription(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["subs"] }),
  });
  const poll = useMutation({ mutationFn: (id: number) => api.pollSubscription(id) });
  const remove = useMutation({
    mutationFn: (id: number) => api.deleteSubscription(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["subs"] }),
  });

  return (
    <div>
      <h1 className="mb-1 text-2xl font-semibold">Subscriptions</h1>
      <p className="mb-6 text-sm text-muted-foreground">
        RSS / RSSHub feeds polled automatically for new content.
      </p>

      <Card className="mb-6 p-4">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (feed.trim()) add.mutate();
          }}
          className="flex flex-wrap items-end gap-3"
        >
          <div className="flex-1">
            <label className="mb-1 block text-xs text-muted-foreground">Feed URL</label>
            <Input
              placeholder="https://rsshub.app/youtube/channel/..."
              value={feed}
              onChange={(e) => setFeed(e.target.value)}
            />
          </div>
          <div className="w-28">
            <label className="mb-1 block text-xs text-muted-foreground">Every (min)</label>
            <Input
              type="number"
              value={interval}
              onChange={(e) => setIntervalMin(e.target.value)}
            />
          </div>
          <Button type="submit" disabled={add.isPending || !feed.trim()}>
            {add.isPending ? <Spinner /> : "Subscribe"}
          </Button>
        </form>
        {add.isError && <p className="mt-2 text-sm text-red-400">{String(add.error)}</p>}
      </Card>

      <div className="space-y-3">
        {(subs.data ?? []).map((s) => (
          <Card key={s.id} className="flex items-center justify-between gap-4 p-4">
            <div className="min-w-0 flex-1">
              <div className="mb-1 flex items-center gap-2">
                <PlatformBadge platform={s.platform} />
                {!s.enabled && (
                  <span className="text-xs text-muted-foreground">paused</span>
                )}
              </div>
              <p className="truncate font-medium">{s.title || s.feed_url}</p>
              <div className="mt-1 flex flex-wrap gap-3 text-xs text-muted-foreground">
                <span>every {s.interval_minutes}m</span>
                <span>
                  {s.last_checked_at
                    ? `checked ${timeAgo(s.last_checked_at)}`
                    : "never checked"}
                </span>
              </div>
            </div>
            <div className="flex gap-2">
              <Button size="sm" variant="outline" onClick={() => poll.mutate(s.id)}>
                <RefreshCw className="h-4 w-4" /> Poll
              </Button>
              <Button size="sm" variant="ghost" onClick={() => toggle.mutate(s.id)}>
                <Power className="h-4 w-4" />
              </Button>
              <Button size="sm" variant="danger" onClick={() => remove.mutate(s.id)}>
                <Trash2 className="h-4 w-4" />
              </Button>
            </div>
          </Card>
        ))}
        {subs.data?.length === 0 && (
          <Card className="p-10 text-center text-muted-foreground">
            No subscriptions yet.
          </Card>
        )}
      </div>
    </div>
  );
}
