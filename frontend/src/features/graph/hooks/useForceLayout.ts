// Bridge between d3-force (physics) and react-flow (rendering)

import {
  applyNodeChanges,
  type OnNodeDrag,
  type OnNodesChange,
} from "@xyflow/react";
import { useCallback, useEffect, useRef, useState } from "react";

import type { GraphNode, GraphResponse } from "../../../types/api";
import { nodeRadius, sizeTier, TIER_DIMENSIONS, topicColor } from "../colors";
import { createSimulation, type SimLink, type SimNode } from "../layout/forceLayout";
import { corpusKey, loadPositions, type PositionMap, savePositions, seedPosition } from "../layout/positions";
import type { ConnectionFlowEdge, DocFlowNode } from "../types";

interface ForceLayout {
  nodes: DocFlowNode[];
  edges: ConnectionFlowEdge[];
  isSettled: boolean;
  onNodesChange: OnNodesChange<DocFlowNode>;
  onNodeDragStart: OnNodeDrag<DocFlowNode>;
  onNodeDrag: OnNodeDrag<DocFlowNode>;
  onNodeDragStop: OnNodeDrag<DocFlowNode>;
}

type Dims = { width: number; height: number };

export function useForceLayout(graph: GraphResponse | undefined): ForceLayout {
  const [nodes, setNodes] = useState<DocFlowNode[]>([]);
  const [edges, setEdges] = useState<ConnectionFlowEdge[]>([]);
  const [isSettled, setIsSettled] = useState(false);

  const simRef = useRef<ReturnType<typeof createSimulation> | null>(null);
  const simNodesRef = useRef<Map<string, SimNode>>(new Map());
  const dimsRef = useRef<Map<string, Dims>>(new Map());
  const keyRef = useRef<string>("");

  const saveCurrent = useCallback(() => {
    if (!keyRef.current || simNodesRef.current.size === 0) return;
    const positions: PositionMap = {};
    for (const [id, s] of simNodesRef.current) {
      if (s.x !== undefined && s.y !== undefined) {
        positions[id] = { x: Math.round(s.x), y: Math.round(s.y) };
      }
    }
    savePositions(keyRef.current, positions);
  }, []);

  useEffect(() => {
    if (!graph || graph.nodes.length === 0) {
      simRef.current = null;
      simNodesRef.current = new Map();
      keyRef.current = "";
      setNodes([]);
      setEdges([]);
      setIsSettled(false);
      return;
    }
    
    setIsSettled(false);

    const key = corpusKey(graph.nodes.map((n) => n.id));
    const saved = loadPositions(key) ?? {};
    const count = graph.nodes.length;

    const simNodes: SimNode[] = graph.nodes.map((n, i) => {
      const seed = saved[n.id] ?? seedPosition(i, count);
      return { id: n.id, radius: nodeRadius(n.size_bytes), x: seed.x, y: seed.y };
    });
    const byId = new Map(simNodes.map((s) => [s.id, s]));
    const dims = new Map<string, Dims>(
      graph.nodes.map((n) => [n.id, TIER_DIMENSIONS[sizeTier(n.size_bytes)]]),
    );
    const idSet = new Set(byId.keys());
    const links: SimLink[] = graph.edges
      .filter((e) => idSet.has(e.source) && idSet.has(e.target))
      .map((e) => ({ source: e.source, target: e.target, combined_score: e.combined_score }));

    simNodesRef.current = byId;
    dimsRef.current = dims;
    keyRef.current = key;

    const toPosition = (id: string) => {
      const s = byId.get(id);
      const d = dims.get(id);
      if (!s || !d) return { x: 0, y: 0 };
      // sim coordinates are centers; react-flow positions are top-left corners
      return { x: (s.x ?? 0) - d.width / 2, y: (s.y ?? 0) - d.height / 2 };
    };

    setNodes(
      graph.nodes.map(
        (n: GraphNode): DocFlowNode => ({
          id: n.id,
          type: "doc",
          position: toPosition(n.id),
          width: dims.get(n.id)?.width,
          height: dims.get(n.id)?.height,
          data: {
            node: n,
            topicColor: topicColor(n.dominant_topic_id),
            dim: false,
            selected: false,
          },
        }),
      ),
    );
    setEdges(
      graph.edges.map(
        (e): ConnectionFlowEdge => ({
          id: e.id,
          source: e.source,
          target: e.target,
          type: "connection",
          data: { edge: e, dim: false, selected: false, hovered: false },
        }),
      ),
    );

    const sim = createSimulation(simNodes, links);
    simRef.current = sim;

    let dirty = false;
    let settledSaved = false;
    sim.on("tick", () => {
      dirty = true;
      if (!settledSaved && sim.alpha() < 0.03) {
        settledSaved = true;
        setIsSettled(true);
        saveCurrent();
      }
    });

    let raf = requestAnimationFrame(function flush() {
      if (dirty) {
        dirty = false;
        setNodes((prev) => prev.map((fn) => ({ ...fn, position: toPosition(fn.id) })));
      }
      raf = requestAnimationFrame(flush);
    });

    return () => {
      cancelAnimationFrame(raf);
      sim.stop();
      saveCurrent();
    };
  }, [graph, saveCurrent]);

  const onNodesChange: OnNodesChange<DocFlowNode> = useCallback((changes) => {
    setNodes((nds) => applyNodeChanges(changes, nds));
  }, []);

  const pin = useCallback((node: DocFlowNode) => {
    const s = simNodesRef.current.get(node.id);
    const d = dimsRef.current.get(node.id);
    if (!s || !d) return;
    s.fx = node.position.x + d.width / 2;
    s.fy = node.position.y + d.height / 2;
  }, []);

  const onNodeDragStart: OnNodeDrag<DocFlowNode> = useCallback(
    (_event, node) => {
      pin(node);
      simRef.current?.alphaTarget(0.3).restart();
    },
    [pin],
  );

  const onNodeDrag: OnNodeDrag<DocFlowNode> = useCallback(
    (_event, node) => {
      pin(node);
    },
    [pin],
  );

  const onNodeDragStop: OnNodeDrag<DocFlowNode> = useCallback(
    (_event, node) => {
      const s = simNodesRef.current.get(node.id);
      if (s) {
        s.fx = null;
        s.fy = null;
      }
      simRef.current?.alphaTarget(0);
      saveCurrent();
    },
    [saveCurrent],
  );

  return { nodes, edges, isSettled, onNodesChange, onNodeDragStart, onNodeDrag, onNodeDragStop };
}
