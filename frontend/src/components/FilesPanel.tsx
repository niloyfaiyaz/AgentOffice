import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef } from "react";
import { api } from "../api";
import { Badge, Button, Card, ErrorText } from "../ui";

interface RefFile { id: string; filename: string; size_bytes: number; chars: number; extraction_status: string; extraction_note: string }

export function FilesPanel({ pid }: { pid: string }) {
  const qc = useQueryClient();
  const input = useRef<HTMLInputElement>(null);
  const files = useQuery({ queryKey: ["files", pid], queryFn: () => api.get<RefFile[]>(`/projects/${pid}/files`) });
  const up = useMutation({ mutationFn: (f: File) => api.upload(`/projects/${pid}/files`, f), onSuccess: () => qc.invalidateQueries({ queryKey: ["files", pid] }) });
  const del = useMutation({ mutationFn: (id: string) => api.del(`/projects/${pid}/files/${id}`), onSuccess: () => qc.invalidateQueries({ queryKey: ["files", pid] }) });
  return (
    <Card title="Reference material" actions={<Button onClick={() => input.current?.click()} disabled={up.isPending}>{up.isPending ? "Uploading…" : "Upload file"}</Button>}>
      <input ref={input} type="file" className="hidden" aria-label="Upload reference file"
        accept=".txt,.md,.pdf,.docx,.csv,.json,.py,.js,.ts,.tsx,.java,.go,.rb,.html,.css,.sql,.yaml,.yml"
        onChange={(e) => { const f = e.target.files?.[0]; if (f) up.mutate(f); e.target.value = ""; }} />
      <p className="mb-2 text-xs text-muted">TXT, Markdown, PDF, DOCX, CSV, JSON or source code, up to 10 MB. Contents are treated as untrusted data and
        only shared with the AI providers your agents use.</p>
      <ErrorText error={up.error || del.error} />
      {files.data?.length ? (
        <ul className="divide-y divide-line text-sm">
          {files.data.map((f) => (
            <li key={f.id} className="flex items-center justify-between gap-2 py-1.5">
              <span className="min-w-0 truncate">{f.filename} <span className="text-xs text-muted">· {(f.size_bytes / 1024).toFixed(1)} KB · {f.chars} chars</span></span>
              <span className="flex items-center gap-2">
                <Badge tone={f.extraction_status === "ok" ? "ok" : "warn"} title={f.extraction_note}>{f.extraction_status}</Badge>
                <Button variant="ghost" onClick={() => del.mutate(f.id)} aria-label={`Remove ${f.filename}`}>Remove</Button>
              </span>
            </li>
          ))}
        </ul>
      ) : <p className="text-sm text-muted">No files yet (optional).</p>}
    </Card>
  );
}
