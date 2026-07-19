/** Pure d3-force simulation factory. react-flow renders; this owns physics.
 *  Link distance/strength derive from combined_score so the layout itself
 *  encodes relatedness — strongly linked documents literally sit closer. */

import {
  forceCollide,
  forceLink,
  forceManyBody,
  forceSimulation,
  forceX,
  forceY,
  type Simulation,
  type SimulationLinkDatum,
  type SimulationNodeDatum,
} from "d3-force";

export interface SimNode extends SimulationNodeDatum {
  id: string;
  /** Collision radius (half the node-card diagonal). */
  radius: number;
}

export interface SimLink extends SimulationLinkDatum<SimNode> {
  combined_score: number;
}

export function createSimulation(
  nodes: SimNode[],
  links: SimLink[],
): Simulation<SimNode, SimLink> {
  return forceSimulation<SimNode>(nodes)
    .force(
      "link",
      forceLink<SimNode, SimLink>(links)
        .id((d) => d.id)
        .distance((l) => 240 - 140 * l.combined_score)
        .strength((l) => 0.2 + 0.6 * l.combined_score),
    )
    .force("charge", forceManyBody().strength(-380))
    .force(
      "collide",
      forceCollide<SimNode>().radius((n) => n.radius + 24),
    )
    // Soft centering beats forceCenter for drag behavior: dragged nodes don't
    // yank the whole graph back toward the origin.
    .force("x", forceX(0).strength(0.04))
    .force("y", forceY(0).strength(0.04))
    .alphaDecay(0.05); // settles in ~2s — organic drift, Obsidian-style
}
