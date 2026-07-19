import clsx from "clsx";
import { CornerDownLeft, MessageCircleQuestion, ShieldOff } from "lucide-react";
import { useRef, useState } from "react";

import type { EvidencePanelHandle } from "./EvidencePanel";
import { AnswerView } from "./AnswerView";
import { EvidencePanel } from "./EvidencePanel";
import { useAsk } from "./useAsk";

function InitialState() {
  return (
    <div className="flex flex-col items-center rounded-lg border border-border bg-surface/40 px-6 py-16 text-center">
      <div className="flex size-12 items-center justify-center rounded-lg border border-border bg-surface">
        <MessageCircleQuestion className="size-6 text-muted" strokeWidth={1.5} />
      </div>
      <h2 className="mt-5 text-sm font-semibold">Ask your corpus</h2>
      <p className="mt-1.5 max-w-sm text-sm leading-relaxed text-muted">
        Hybrid retrieval finds the passages; the local model answers from them — and only
        them. Every claim is cited, every retrieved passage is shown.
      </p>
    </div>
  );
}

function LoadingState() {
  return (
    <div className="flex items-center gap-3.5 rounded-lg border border-border bg-surface/40 px-5 py-4">
      <svg
        viewBox="0 0 16 16"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
        className="size-4 shrink-0 animate-spin text-accent motion-reduce:animate-none"
        aria-hidden="true"
      >
        <path d="M8 1.5A6.5 6.5 0 1 1 1.5 8" />
      </svg>
      <div className="text-sm text-muted">
        Retrieving evidence and generating with the local model…
        <span className="mt-0.5 block text-xs">
          The first question can take 10–30 s on CPU — the model loads once.
        </span>
      </div>
    </div>
  );
}

export function AskPage() {
  const [question, setQuestion] = useState("");
  const mutation = useAsk();
  const result = mutation.data;
  const evidenceRef = useRef<EvidencePanelHandle>(null);

  const submit = () => {
    const trimmed = question.trim();
    if (trimmed && !mutation.isPending) mutation.mutate({ question: trimmed });
  };

  const rateLimited = mutation.isError && mutation.error.status === 429;

  return (
    <div className="mx-auto max-w-4xl px-8 py-10">
      <header className="mb-8">
        <h1 className="text-2xl font-bold tracking-tight">Ask</h1>
        <p className="mt-1.5 text-sm text-muted">
          Grounded answers from your corpus — every claim cited, every retrieved passage shown.
        </p>
      </header>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          submit();
        }}
        className="flex items-start gap-2"
      >
        <div className="relative flex-1">
          <textarea
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            onKeyDown={(e) => {
              // Enter submits; Shift+Enter inserts a newline.
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                submit();
              }
            }}
            placeholder="What does the corpus say about…"
            rows={3}
            autoFocus
            className={clsx(
              "w-full resize-none rounded-lg border border-border bg-surface px-4 py-3 pr-12 text-sm",
              "placeholder:text-muted/70 transition-colors duration-150",
              "hover:border-border focus:border-accent/60 focus:outline-none",
            )}
          />
          <CornerDownLeft
            className="pointer-events-none absolute right-3.5 top-3.5 size-3.5 text-muted/50"
            strokeWidth={1.75}
          />
        </div>
        <button
          type="submit"
          disabled={mutation.isPending || !question.trim()}
          className={clsx(
            "rounded-lg bg-accent px-4 py-3 text-sm font-medium text-white",
            "transition-colors duration-150 hover:bg-accent-hover",
            "disabled:cursor-not-allowed disabled:opacity-50",
          )}
        >
          {mutation.isPending ? "Asking…" : "Ask"}
        </button>
      </form>

      <div className="mt-8 space-y-4">
        {mutation.isPending && <LoadingState />}

        {rateLimited && (
          <div className="rounded-lg border border-sig-top/25 bg-sig-top/10 px-4 py-3 text-sm text-sig-top">
            The local model is busy — try again shortly.
          </div>
        )}
        {mutation.isError && !rateLimited && (
          <div className="rounded-lg border border-red-400/20 bg-red-400/10 px-4 py-3 text-sm text-red-300">
            {mutation.error.detail}
          </div>
        )}

        {result && result.generator === "llm" && (
          <>
            <AnswerView result={result} onCite={(m) => evidenceRef.current?.jumpTo(m)} />
            <EvidencePanel result={result} handleRef={evidenceRef} />
          </>
        )}

        {result && result.generator === "unavailable" && (
          <>
            <div className="flex items-start gap-3 rounded-lg border border-border bg-surface/40 px-5 py-4">
              <ShieldOff className="mt-0.5 size-4 shrink-0 text-muted" strokeWidth={1.75} />
              <p className="text-sm leading-relaxed text-muted">
                <span className="font-medium text-text">Local LLM unavailable</span> — showing
                the retrieved evidence only. The passages below are what the answer would be
                grounded on.
              </p>
            </div>
            <EvidencePanel result={result} collapsible={false} />
          </>
        )}

        {result && result.generator === "no_evidence" && (
          <div className="rounded-lg border border-border bg-surface/40 px-6 py-12 text-center text-sm text-muted">
            Nothing in the corpus matched this question. Try different terms — or upload more
            documents.
          </div>
        )}

        {!result && !mutation.isError && !mutation.isPending && <InitialState />}
      </div>
    </div>
  );
}
