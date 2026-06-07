import {
  forwardRef,
  useCallback,
  useEffect,
  useImperativeHandle,
  useMemo,
  useRef,
  useState,
} from "react";
import ForceGraph2D from "react-force-graph-2d";
import type { GraphData, GraphNode } from "@/lib/api";

export interface GraphCanvasHandle {
  focusNode: (id: number) => void;
  zoomToFit: () => void;
}

type FGNode = GraphNode & { x?: number; y?: number; fx?: number; fy?: number };
type FGLink = { source: number | FGNode; target: number | FGNode; weight: number };

// Stable, well-spread color per community (golden-angle hue).
function communityColor(community: number): string {
  const hue = (community * 137.508) % 360;
  return `hsl(${hue}, 65%, 60%)`;
}

function nodeRadius(node: GraphNode): number {
  return 3 + Math.sqrt(node.degree + 1) * 1.3;
}

function snippet(node: GraphNode, n: number): string {
  const t = (node.text || node.title || "").replace(/\s+/g, " ").trim();
  return t.length > n ? t.slice(0, n - 1) + "…" : t;
}

export const GraphCanvas = forwardRef<GraphCanvasHandle, {
  data: GraphData;
  selectedId: number | null;
  onSelect: (id: number) => void;
}>(function GraphCanvas({ data, selectedId, onSelect }, ref) {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const fgRef = useRef<any>(null);
  const wrapRef = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ width: 600, height: 500 });
  const [hoverNode, setHoverNode] = useState<number | null>(null);

  const adjacency = useMemo(() => {
    const map = new Map<number, Set<number>>();
    for (const e of data.edges) {
      if (!map.has(e.source)) map.set(e.source, new Set());
      if (!map.has(e.target)) map.set(e.target, new Set());
      map.get(e.source)!.add(e.target);
      map.get(e.target)!.add(e.source);
    }
    return map;
  }, [data.edges]);

  const graphData = useMemo(
    () => ({
      nodes: data.nodes.map((n) => ({ ...n })) as FGNode[],
      links: data.edges.map((e) => ({
        source: e.source,
        target: e.target,
        weight: e.weight,
      })) as FGLink[],
    }),
    [data],
  );

  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const ro = new ResizeObserver(() => {
      setSize({ width: el.clientWidth, height: el.clientHeight });
    });
    ro.observe(el);
    setSize({ width: el.clientWidth, height: el.clientHeight });
    return () => ro.disconnect();
  }, []);

  const focusNode = useCallback((id: number) => {
    const fg = fgRef.current;
    if (!fg) return;
    const node = (graphData.nodes as FGNode[]).find((n) => n.id === id);
    if (node && node.x !== undefined && node.y !== undefined) {
      fg.centerAt(node.x, node.y, 600);
      fg.zoom(3, 600);
    }
  }, [graphData]);

  useImperativeHandle(ref, () => ({
    focusNode,
    zoomToFit: () => fgRef.current?.zoomToFit(500, 60),
  }));

  useEffect(() => {
    const t = setTimeout(() => fgRef.current?.zoomToFit(500, 60), 700);
    return () => clearTimeout(t);
  }, [graphData]);

  const highlighted = useMemo(() => {
    if (hoverNode == null) return null;
    const set = new Set<number>([hoverNode]);
    adjacency.get(hoverNode)?.forEach((n) => set.add(n));
    return set;
  }, [hoverNode, adjacency]);

  return (
    <div ref={wrapRef} className="h-full w-full">
      <ForceGraph2D
        ref={fgRef}
        width={size.width}
        height={size.height}
        graphData={graphData}
        nodeId="id"
        cooldownTicks={120}
        d3VelocityDecay={0.3}
        nodeLabel={(n: FGNode) =>
          `<div style="max-width:280px"><b>${(n.title ?? "").replace(/</g, "&lt;")}</b><br/>${snippet(n, 160).replace(/</g, "&lt;")}</div>`
        }
        onNodeHover={(n: FGNode | null) => setHoverNode(n ? n.id : null)}
        onNodeClick={(n: FGNode) => onSelect(n.id)}
        onNodeDragEnd={(n: FGNode) => {
          n.fx = n.x;
          n.fy = n.y;
        }}
        linkColor={(l: FGLink) =>
          highlighted && highlighted.has((l.source as FGNode).id) &&
          highlighted.has((l.target as FGNode).id)
            ? "rgba(120,160,255,0.85)"
            : highlighted
              ? "rgba(140,140,160,0.06)"
              : "rgba(140,140,160,0.22)"
        }
        linkWidth={(l: FGLink) => Math.max(0.4, l.weight * 2.5)}
        nodeCanvasObject={(node: FGNode, ctx, globalScale) => {
          const r = nodeRadius(node);
          const faded = highlighted != null && !highlighted.has(node.id);
          const isSelected = node.id === selectedId;
          ctx.globalAlpha = faded ? 0.15 : 1;

          ctx.beginPath();
          ctx.arc(node.x!, node.y!, r, 0, 2 * Math.PI);
          ctx.fillStyle = communityColor(node.community);
          ctx.fill();
          if (isSelected) {
            ctx.lineWidth = 2 / globalScale;
            ctx.strokeStyle = "#fff";
            ctx.stroke();
          }

          const showLabel =
            globalScale > 2.2 || isSelected || (highlighted?.has(node.id) ?? false);
          if (showLabel && !faded) {
            const fontSize = Math.max(9 / globalScale, 2.5);
            ctx.font = `${fontSize}px Inter, system-ui, sans-serif`;
            ctx.textAlign = "center";
            ctx.textBaseline = "top";
            ctx.fillStyle = "rgba(130,130,150,0.95)";
            ctx.fillText(snippet(node, 24), node.x!, node.y! + r + 1);
          }
          ctx.globalAlpha = 1;
        }}
        nodePointerAreaPaint={(node: FGNode, color: string, ctx: CanvasRenderingContext2D) => {
          ctx.fillStyle = color;
          ctx.beginPath();
          ctx.arc(node.x!, node.y!, nodeRadius(node) + 2, 0, 2 * Math.PI);
          ctx.fill();
        }}
      />
    </div>
  );
});
