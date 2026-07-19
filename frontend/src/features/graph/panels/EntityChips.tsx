import clsx from "clsx";

/** Normalized chip input — EdgePanel maps SharedEntity (count_a/count_b) and
 *  NodePanel maps EntityWeight (count) onto this shape. */
export interface ChipEntity {
  text: string;
  label: string;
  idf: number;
  count: number;
  title?: string;
}

/** Entity pills, idf-desc. Rarity encoding (spec §2 EntityChips): trailing
 *  cyan dot opacity = idf tercile within this list; the top-idf entities get
 *  the stronger "rare" tint when their idf clears 1.0 (i.e. they appear in a
 *  minority of the corpus). */
export function EntityChips({ entities }: { entities: ChipEntity[] }) {
  if (entities.length === 0) {
    return <p className="text-xs text-muted">No shared entities.</p>;
  }
  const sorted = [...entities].sort((a, b) => b.idf - a.idf);
  const maxIdf = sorted[0].idf;

  return (
    <div className="flex flex-wrap gap-[7px]">
      {sorted.map((entity, i) => {
        const tercile = i / sorted.length;
        const dotOpacity = tercile < 1 / 3 ? 1 : tercile < 2 / 3 ? 0.65 : 0.35;
        const rare = maxIdf > 1 && entity.idf >= maxIdf * 0.98;
        return (
          <span
            key={`${entity.text}:${entity.label}`}
            className={clsx(
              "inline-flex items-center gap-1.5 rounded-full px-2.5 py-[5px] text-[11px] font-medium text-text",
              "border transition-all duration-150 hover:-translate-y-px",
              rare
                ? "border-[color-mix(in_oklab,var(--color-sig-ent)_45%,var(--color-border))] bg-[color-mix(in_oklab,var(--color-sig-ent)_13%,var(--color-surface))]"
                : "border-[color-mix(in_oklab,var(--color-sig-ent)_22%,var(--color-border))] bg-[color-mix(in_oklab,var(--color-sig-ent)_7%,var(--color-surface))] hover:border-[color-mix(in_oklab,var(--color-sig-ent)_45%,var(--color-border))]",
            )}
            title={entity.title ?? `${entity.label} · idf ${entity.idf.toFixed(2)}`}
          >
            {entity.text}
            <i className="size-1.5 rounded-full bg-sig-ent" style={{ opacity: dotOpacity }} />
            <small
              className={clsx(
                "font-mono text-[9.5px] font-medium",
                rare ? "text-sig-ent" : "text-muted",
              )}
            >
              {rare ? "rare" : `×${entity.count}`}
            </small>
          </span>
        );
      })}
    </div>
  );
}
