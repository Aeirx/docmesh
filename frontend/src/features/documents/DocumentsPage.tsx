import { DocumentList } from "./DocumentList";
import { Dropzone } from "./Dropzone";
import { useDocuments } from "./useDocuments";

export function DocumentsPage() {
  const { data } = useDocuments();
  const total = data?.total;

  return (
    <div className="mx-auto max-w-4xl px-8 py-10">
      <header className="mb-8">
        <h1 className="text-2xl font-bold tracking-tight">Documents</h1>
        <p className="mt-1.5 text-sm text-muted">
          {total !== undefined && total > 0
            ? `${total} document${total === 1 ? "" : "s"} in your mesh`
            : "Upload documents to build your searchable, connected corpus."}
        </p>
      </header>

      <Dropzone />

      <div className="mt-8">
        <DocumentList />
      </div>
    </div>
  );
}
