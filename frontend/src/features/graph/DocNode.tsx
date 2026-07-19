import { Handle, Position, type NodeProps } from "@xyflow/react";
import clsx from "clsx";
import { motion } from "framer-motion";
import { memo } from "react";

import { formatBytes, middleEllipsis } from "../../lib/format";
import type { FileType } from "../../types/api";
import { sizeTier } from "./colors";
import type { DocFlowNode } from "./types";

/** One icon family: the designer's sheet+fold glyph with a bold type label —
 *  a single stroke width across every file type (spec §2, DocNode). */
const GLYPH_LABELS: Record<FileType, string> = {
  pdf: "PDF",
  docx: "DOC",
  txt: "TXT",
  md: "MD",
};

function FileGlyph({ fileType }: { fileType: FileType }) {
  const label = GLYPH_LABELS[fileType] ?? fileType.toUpperCase().slice(0, 3);
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.5}
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z" />
      <path d="M14 3v5h5" />
      <text
        x="12"
        y="17.5"
        textAnchor="middle"
        fontSize={label.length > 2 ? 6 : 6.5}
        fontWeight={700}
        fill="currentColor"
        stroke="none"
        fontFamily="Inter, system-ui, sans-serif"
        letterSpacing=".4"
      >
        {label}
      </text>
    </svg>
  );
}

export const DocNode = memo(function DocNode({ data }: NodeProps<DocFlowNode>) {
  const { node, topicColor, dim, selected, matchCount, pulseKey } = data;
  const tier = sizeTier(node.size_bytes);

  return (
    <motion.div
      initial={{ opacity: 0, scale: 0.5, filter: "brightness(2) blur(4px)" }}
      animate={{ opacity: 1, scale: 1, filter: "brightness(1) blur(0px)" }}
      transition={{ duration: 0.6, type: "spring", bounce: 0.5 }}
      className="relative h-full w-full"
    >
      <motion.div
        animate={{ y: [0, -4, 0] }}
        transition={{ duration: 4 + Math.random() * 2, repeat: Infinity, ease: "easeInOut" }}
        className={clsx("dm-node", tier, selected && "is-glow", dim && "is-dim")}
        style={{ "--tc": topicColor } as React.CSSProperties}
        title={node.filename}
      >
        <Handle type="target" position={Position.Top} className="dm-handle" isConnectable={false} />
        <span className="n-icon">
          <FileGlyph fileType={node.file_type} />
        </span>
        <span className="flex min-w-0 flex-1 flex-col gap-0.5">
          <span className="n-name">{middleEllipsis(node.filename, 26)}</span>
          <span className="n-meta">
            {node.file_type.toUpperCase()} · {formatBytes(node.size_bytes)}
          </span>
        </span>
        <span className="n-badge" title={`${node.chunk_count} chunks`}>
          {node.chunk_count}
        </span>
        {/* Query mode: how many of this doc's chunks match. Accent-tinted so it
            reads as "query result", distinct from the topic-tinted chunk badge. */}
        {!dim && matchCount !== undefined && matchCount > 0 && (
          <span
            className="n-badge n-match"
            title={`${matchCount} chunk${matchCount === 1 ? "" : "s"} match the query`}
          >
            {matchCount}
          </span>
        )}
        <Handle type="source" position={Position.Bottom} className="dm-handle" isConnectable={false} />
      </motion.div>
      {/* One-shot pulse when a query lands: keyed by the query so a NEW query
          remounts the overlay and re-fires the animation. Lives OUTSIDE
          .dm-node (overflow:hidden would clip the expanding ring) and carries
          its own --tc since it isn't a .dm-node descendant. The container is
          NOT keyed — that would replay the spawn animation. */}
      {!dim && pulseKey && (
        <span
          key={pulseKey}
          aria-hidden="true"
          className="dm-pulse-once pointer-events-none absolute inset-0 rounded-[10px]"
          style={{ "--tc": topicColor } as React.CSSProperties}
        />
      )}
    </motion.div>
  );
});
