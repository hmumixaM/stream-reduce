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
  focusCluster: (id: number) => void;
  zoomToFit: () => void;
}

type FGNode = GraphNode & { x?: number; y?: number; fx?: number; fy?: number };
type FGLink = { source: number | FGNode; target: number | FGNode; weight: number };

// Stable, well-spread color per cluster id (golden-angle hue).
function clusterColor(id: number): string {
  const hue = (id * 137.508) % 360;
  return `hsl(${hue}, 65%, 60%)`;
}

function nodeRadius(node: GraphNode): number {
  return 4 + Math.sqrt(Math.max(1, node.item_count)) * 1.6;
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

  // Adjacency for hover highlighting.
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

  const focusCluster = useCallback((id: number) => {
    const fg = fgRef.current;
    if (!fg) return;
    const node = (graphData.nodes as FGNode[]).find((n) => n.id === id);
    if (node && node.x !== undefined && node.y !== undefined) {
      fg.centerAt(node.x, node.y, 600);
      fg.zoom(2.5, 600);
    }
  }, [graphData]);

  useImperativeHandle(ref, () => ({
    focusCluster,
    zoomToFit: () => fgRef.current?.zoomToFit(500, 60),
  }));

  // Fit once the layout has had a moment to settle.
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
        nodeLabel={(n: FGNode) => `${n.label} — ${n.item_count} articles`}
        onNodeHover={(n: FGNode | null) => setHoverNode(n ? n.id : null)}
        onNodeClick={(n: FGNode) => onSelect(n.id)}
        onNodeDragEnd={(n: FGNode) => {
          n.fx = n.x;
          n.fy = n.y;
        }}
        linkColor={(l: FGLink) =>
          highlighted && highlighted.has((l.source as FGNode).id) &&
          highlighted.has((l.target as FGNode).id)
            ? "rgba(120,160,255,0.8)"
            : highlighted
              ? "rgba(140,140,160,0.08)"
              : "rgba(140,140,160,0.25)"
        }
        linkWidth={(l: FGLink) => Math.max(0.5, l.weight * 3)}
        nodeCanvasObject={(node: FGNode, ctx, globalScale) => {
          const r = nodeRadius(node);
          const faded = highlighted != null && !highlighted.has(node.id);
          const isSelected = node.id === selectedId;
          ctx.globalAlpha = faded ? 0.18 : 1;

          ctx.beginPath();
          ctx.arc(node.x!, node.y!, r, 0, 2 * Math.PI);
          ctx.fillStyle = clusterColor(node.id);
          ctx.fill();
          if (isSelected) {
            ctx.lineWidth = 2 / globalScale;
            ctx.strokeStyle = "#fff";
            ctx.stroke();
          }

          // Paint labels when zoomed in, hovered/highlighted, or selected.
          const showLabel =
            globalScale > 1.4 || isSelected || (highlighted?.has(node.id) ?? false);
          if (showLabel && !faded) {
            const fontSize = Math.max(10 / globalScale, 2.5);
            ctx.font = `${fontSize}px Inter, system-ui, sans-serif`;
            ctx.textAlign = "center";
            ctx.textBaseline = "top";
            ctx.fillStyle = "rgba(120,120,140,0.95)";
            const label = node.label.length > 28 ? node.label.slice(0, 27) + "…" : node.label;
            ctx.fillText(label, node.x!, node.y! + r + 1);
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
