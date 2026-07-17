import clsx from "clsx";
import { AlertCircle, CheckCircle2, UploadCloud, X } from "lucide-react";
import { useRef, useState } from "react";

import { ApiError } from "../../lib/api";
import { formatBytes } from "../../lib/format";
import { useUploadDocument } from "./useDocuments";

// Client-side pre-checks are UX ONLY — instant feedback before wasting bandwidth.
// They are NOT security: the server independently re-validates everything with a
// streamed size cap, magic-byte sniffing, and filename sanitization, and would
// reject anything these checks miss (or that a modified client skips).
const ACCEPTED_EXTENSIONS = [".pdf", ".docx", ".txt", ".md"];
const MAX_UPLOAD_MB = 25;
const MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024;

interface UploadItem {
  key: string;
  name: string;
  size: number;
  progress: number;
  state: "uploading" | "done" | "error";
  message?: string;
}

function errorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    switch (error.code) {
      case "duplicate_document":
        return "Already in your library — identical content exists.";
      case "too_large":
        return `File exceeds the ${MAX_UPLOAD_MB} MB limit.`;
      case "magic_mismatch":
        return "File content doesn't match its extension.";
      case "unsupported_type":
        return "Unsupported file type — PDF, DOCX, TXT, or MD only.";
      case "zip_bomb":
        return "Archive rejected by safety checks.";
      case "empty_file":
        return "File is empty.";
      case "network_error":
        return "Network error — is the backend running?";
      default:
        return error.detail;
    }
  }
  return "Upload failed unexpectedly.";
}

let itemCounter = 0;

export function Dropzone() {
  const [items, setItems] = useState<UploadItem[]>([]);
  const [dragActive, setDragActive] = useState(false);
  // Counter instead of boolean: dragenter/dragleave fire for every child element,
  // a plain boolean flickers as the cursor crosses inner nodes.
  const dragDepth = useRef(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const upload = useUploadDocument();

  function patchItem(key: string, patch: Partial<UploadItem>) {
    setItems((current) =>
      current.map((item) => (item.key === key ? { ...item, ...patch } : item)),
    );
  }

  function removeItem(key: string) {
    setItems((current) => current.filter((item) => item.key !== key));
  }

  function startUpload(file: File) {
    const key = `upload-${itemCounter++}`;
    const base: UploadItem = {
      key,
      name: file.name,
      size: file.size,
      progress: 0,
      state: "uploading",
    };

    const extension = `.${file.name.split(".").pop()?.toLowerCase() ?? ""}`;
    if (!ACCEPTED_EXTENSIONS.includes(extension)) {
      setItems((c) => [...c, { ...base, state: "error", message: errorMessage(new ApiError(0, "unsupported_type", "")) }]);
      return;
    }
    if (file.size > MAX_UPLOAD_BYTES) {
      setItems((c) => [...c, { ...base, state: "error", message: errorMessage(new ApiError(0, "too_large", "")) }]);
      return;
    }

    setItems((c) => [...c, base]);
    upload
      .mutateAsync({ file, onProgress: (p) => patchItem(key, { progress: p }) })
      .then(() => {
        patchItem(key, { state: "done", progress: 100 });
        // Success rows self-dismiss; the document appears in the list below.
        setTimeout(() => removeItem(key), 2500);
      })
      .catch((error: unknown) => {
        patchItem(key, { state: "error", message: errorMessage(error) });
      });
  }

  function handleFiles(files: FileList | null) {
    if (!files) return;
    for (const file of Array.from(files)) startUpload(file);
  }

  return (
    <section aria-label="Upload documents">
      <div
        role="button"
        tabIndex={0}
        onClick={() => inputRef.current?.click()}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            inputRef.current?.click();
          }
        }}
        onDragEnter={(e) => {
          e.preventDefault();
          dragDepth.current += 1;
          setDragActive(true);
        }}
        onDragOver={(e) => e.preventDefault()}
        onDragLeave={(e) => {
          e.preventDefault();
          dragDepth.current -= 1;
          if (dragDepth.current <= 0) {
            dragDepth.current = 0;
            setDragActive(false);
          }
        }}
        onDrop={(e) => {
          e.preventDefault();
          dragDepth.current = 0;
          setDragActive(false);
          handleFiles(e.dataTransfer.files);
        }}
        className={clsx(
          "group flex cursor-pointer flex-col items-center justify-center rounded-lg border border-dashed px-6 py-12",
          "transition-colors duration-200",
          dragActive
            ? "border-accent bg-accent/5"
            : "border-border bg-surface/40 hover:border-muted/60 hover:bg-surface/70",
        )}
      >
        <div
          className={clsx(
            "flex size-12 items-center justify-center rounded-full transition-colors duration-200",
            dragActive ? "bg-accent/20" : "bg-surface-raised group-hover:bg-accent/10",
          )}
        >
          <UploadCloud
            className={clsx(
              "size-6 transition-colors duration-200",
              dragActive ? "text-accent" : "text-muted group-hover:text-accent",
            )}
            strokeWidth={1.75}
          />
        </div>
        <p className="mt-4 text-sm font-medium">
          {dragActive ? "Release to upload" : "Drop files here, or click to browse"}
        </p>
        <p className="mt-1 text-xs text-muted">
          PDF, DOCX, TXT, MD <span className="mx-1 text-border">·</span> up to {MAX_UPLOAD_MB} MB
        </p>
        <input
          ref={inputRef}
          type="file"
          multiple
          accept=".pdf,.docx,.txt,.md"
          className="hidden"
          onChange={(e) => {
            handleFiles(e.target.files);
            e.target.value = ""; // allow re-selecting the same file
          }}
        />
      </div>

      {items.length > 0 && (
        <ul className="mt-3 space-y-2">
          {items.map((item) => (
            <li
              key={item.key}
              className="flex items-center gap-3 rounded-lg border border-border bg-surface px-4 py-2.5"
            >
              {item.state === "error" ? (
                <AlertCircle className="size-4 shrink-0 text-red-400" strokeWidth={2} />
              ) : item.state === "done" ? (
                <CheckCircle2 className="size-4 shrink-0 text-emerald-400" strokeWidth={2} />
              ) : (
                <UploadCloud className="size-4 shrink-0 text-accent" strokeWidth={2} />
              )}

              <div className="min-w-0 flex-1">
                <div className="flex items-baseline justify-between gap-3">
                  <p className="truncate text-sm font-medium">{item.name}</p>
                  <span className="shrink-0 font-mono text-xs text-muted">
                    {formatBytes(item.size)}
                  </span>
                </div>
                {item.state === "uploading" && (
                  <div className="mt-1.5 h-1 overflow-hidden rounded-full bg-surface-raised">
                    <div
                      className="h-full rounded-full bg-accent transition-[width] duration-200"
                      style={{ width: `${item.progress}%` }}
                    />
                  </div>
                )}
                {item.state === "error" && (
                  <p className="mt-0.5 text-xs text-red-400">{item.message}</p>
                )}
              </div>

              {item.state !== "uploading" && (
                <button
                  type="button"
                  onClick={() => removeItem(item.key)}
                  aria-label={`Dismiss ${item.name}`}
                  className="shrink-0 rounded-md p-1 text-muted transition-colors duration-150 hover:bg-surface-raised hover:text-text"
                >
                  <X className="size-4" strokeWidth={2} />
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
