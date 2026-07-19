import {
  Background,
  BackgroundVariant,
  Controls,
  MiniMap,
  ReactFlow,
  type EdgeMouseHandler,
  type EdgeTypes,
  type NodeMouseHandler,
  type NodeTypes,
  type OnNodeDrag,
  type OnNodesChange,
  type ReactFlowInstance,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import clsx from "clsx";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { ConnectionEdge } from "./ConnectionEdge";
import { DocNode } from "./DocNode";
import { EdgeTooltip } from "./EdgeTooltip";
import type { ConnectionFlowEdge, DocFlowNode } from "./types";
import { HoverContext } from "./context";

/** Module-scope registries — recreating these per render forces react-flow to
 *  remount every node/edge. */
const NODE_TYPES: NodeTypes = { doc: DocNode };
const EDGE_TYPES: EdgeTypes = { connection: ConnectionEdge };

const TOOLTIP_W = 200;
const TOOLTIP_H = 150;

interface GraphCanvasProps {
  nodes: DocFlowNode[];
  edges: ConnectionFlowEdge[];
  weights: Record<string, number>;
  /** Shifts minimap/controls left while a side panel is open. */
  panelOpen: boolean;
  isSettled: boolean;
  onNodesChange: OnNodesChange<DocFlowNode>;
  onNodeDragStart: OnNodeDrag<DocFlowNode>;
  onNodeDrag: OnNodeDrag<DocFlowNode>;
  onNodeDragStop: OnNodeDrag<DocFlowNode>;
  onSelectNode: (id: string) => void;
  onSelectEdge: (source: string, target: string) => void;
  onClearSelection: () => void;
}

export function GraphCanvas({
  nodes,
  edges,
  weights,
  panelOpen,
  isSettled,
  onNodesChange,
  onNodeDragStart,
  onNodeDrag,
  onNodeDragStop,
  onSelectNode,
  onSelectEdge,
  onClearSelection,
}: GraphCanvasProps) {
  const wrapperRef = useRef<HTMLDivElement>(null);
  const [hoveredEdgeId, setHoveredEdgeId] = useState<string | null>(null);
  const [tooltipPos, setTooltipPos] = useState<{ x: number; y: number }>({ x: 0, y: 0 });

  const edgesById = useMemo(() => new Map(edges.map((e) => [e.id, e])), [edges]);
  const hoveredEdge = hoveredEdgeId ? edgesById.get(hoveredEdgeId)?.data?.edge ?? null : null;

  const moveTooltip = useCallback((event: React.MouseEvent) => {
    const rect = wrapperRef.current?.getBoundingClientRect();
    if (!rect) return;
    setTooltipPos({
      x: Math.min(Math.max(event.clientX - rect.left + 14, 8), rect.width - TOOLTIP_W),
      y: Math.min(Math.max(event.clientY - rect.top + 16, 8), rect.height - TOOLTIP_H),
    });
  }, []);

  const onEdgeMouseEnter: EdgeMouseHandler<ConnectionFlowEdge> = useCallback(
    (event, edge) => {
      setHoveredEdgeId(edge.id);
      moveTooltip(event);
    },
    [moveTooltip],
  );
  const onEdgeMouseMove: EdgeMouseHandler<ConnectionFlowEdge> = useCallback(
    (event) => moveTooltip(event),
    [moveTooltip],
  );
  const onEdgeMouseLeave: EdgeMouseHandler<ConnectionFlowEdge> = useCallback(
    () => setHoveredEdgeId(null),
    [],
  );

  const onNodeClick: NodeMouseHandler<DocFlowNode> = useCallback(
    (_event, node) => onSelectNode(node.id),
    [onSelectNode],
  );
  const onEdgeClick: EdgeMouseHandler<ConnectionFlowEdge> = useCallback(
    (_event, edge) => onSelectEdge(edge.source, edge.target),
    [onSelectEdge],
  );

  const [instance, setInstance] = useState<ReactFlowInstance<
    DocFlowNode,
    ConnectionFlowEdge
  > | null>(null);

  useEffect(() => {
    if (instance && isSettled && nodes.length > 0) {
      void instance.fitView({ padding: 0.2, duration: 400 });
    }
  }, [instance, isSettled, nodes.length]);

  return (
    <div
      ref={wrapperRef}
      className={clsx("dm-canvas relative h-full w-full", panelOpen && "panel-open")}
    >
      <HoverContext.Provider value={hoveredEdgeId}>
        <ReactFlow<DocFlowNode, ConnectionFlowEdge>
          nodes={nodes}
          edges={edges}
        nodeTypes={NODE_TYPES}
        edgeTypes={EDGE_TYPES}
        colorMode="dark"
        onInit={setInstance}
        onNodesChange={onNodesChange}
        onNodeDragStart={onNodeDragStart}
        onNodeDrag={onNodeDrag}
        onNodeDragStop={onNodeDragStop}
        onNodeClick={onNodeClick}
        onEdgeClick={onEdgeClick}
        onEdgeMouseEnter={onEdgeMouseEnter}
        onEdgeMouseMove={onEdgeMouseMove}
        onEdgeMouseLeave={onEdgeMouseLeave}
        onPaneClick={onClearSelection}
        minZoom={0.3}
        maxZoom={2}
        nodesConnectable={false}
        selectNodesOnDrag={false}
        zoomOnDoubleClick={false}
        deleteKeyCode={null}
        proOptions={{ hideAttribution: true }}
      >
        <Background variant={BackgroundVariant.Dots} gap={24} size={1} color="#1e2331" />
        <MiniMap
          position="bottom-right"
          style={{ marginBottom: 118, width: 166, height: 100 }}
          pannable
          nodeColor={(n) => (n as DocFlowNode).data.topicColor}
          nodeStrokeWidth={0}
          nodeBorderRadius={2}
          maskColor="rgba(12,14,20,.62)"
          maskStrokeColor="rgba(230,232,238,.22)"
          maskStrokeWidth={1}
        />
        <Controls position="bottom-right" showInteractive={false} orientation="vertical" />
      </ReactFlow>
      </HoverContext.Provider>

      {hoveredEdge && (
        <EdgeTooltip edge={hoveredEdge} weights={weights} x={tooltipPos.x} y={tooltipPos.y} />
      )}
    </div>
  );
}
