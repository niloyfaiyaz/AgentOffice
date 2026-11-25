import { useEffect, useRef, type ButtonHTMLAttributes, type ReactNode } from "react";
import * as RD from "@radix-ui/react-dialog";
import { STATUS_LABEL, type Avatar } from "./api";
import { CHAR_H, CHAR_W, drawFrame } from "./office/sprites";

type Variant = "primary" | "secondary" | "danger" | "ghost";

export function Button({ variant = "secondary", className = "", ...p }: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant }) {
  const styles: Record<Variant, string> = {
    primary: "bg-accent text-accentInk hover:brightness-110 border-transparent",
    secondary: "bg-panel2 text-ink hover:brightness-110 border-line",
    danger: "bg-bad/90 text-white hover:brightness-110 border-transparent",
    ghost: "bg-transparent text-ink hover:bg-panel2 border-transparent",
  };
  return (
    <button
      {...p}
      className={`inline-flex items-center justify-center gap-1.5 rounded-md border px-3 py-1.5 text-sm font-medium
        disabled:opacity-50 disabled:cursor-not-allowed focus-visible:outline focus-visible:outline-2
        focus-visible:outline-offset-2 focus-visible:outline-accent ${styles[variant]} ${className}`}
    />
  );
}

export function Card({ title, actions, children, className = "" }: { title?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={`min-w-0 rounded-lg border border-line bg-panel p-4 ${className}`}>
      {(title || actions) && (
        <header className="mb-3 flex flex-wrap items-center justify-between gap-2">
          {title && <h2 className="text-base font-semibold text-ink">{title}</h2>}
          {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
        </header>
      )}
      {children}
    </section>
  );
}

const TONE: Record<string, string> = {
  ok: "bg-ok/15 text-ok border-ok/30", warn: "bg-warn/15 text-warn border-warn/30", bad: "bg-bad/15 text-bad border-bad/30",
  info: "bg-info/15 text-info border-info/30", muted: "bg-panel2 text-muted border-line",
};

export function statusTone(s: string): keyof typeof TONE {
  if (["completed", "valid", "approved", "accepted", "resolved", "answered", "ok"].includes(s)) return "ok";
  if (["failed", "invalid", "blocked", "rejected", "error", "critical", "unresolved", "cancelled"].includes(s)) return "bad";
  if (["waiting_for_client", "awaiting_approval", "waiting_approval", "pending", "paused", "pausing", "major",
       "revision_requested", "rework_requested", "open", "unvalidated"].includes(s)) return "warn";
  if (["working", "running", "reviewing", "communicating", "planning", "assigned", "ready", "waiting_subtask"].includes(s)) return "info";
  return "muted";
}

export function Badge({ children, tone = "muted", title }: { children: ReactNode; tone?: keyof typeof TONE; title?: string }) {
  return <span title={title} className={`inline-flex items-center rounded border px-1.5 py-0.5 text-xs font-medium ${TONE[tone]}`}>{children}</span>;
}

export function StatusBadge({ status }: { status: string }) {
  return <Badge tone={statusTone(status)}>{STATUS_LABEL[status] ?? status.replace(/_/g, " ")}</Badge>;
}

export function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <label className="block text-sm">
      <span className="mb-1 block font-medium text-ink">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-xs text-muted">{hint}</span>}
    </label>
  );
}

export const inputCls =
  "w-full max-w-full min-w-0 rounded-md border border-line bg-bg px-2.5 py-1.5 text-sm text-ink placeholder:text-muted focus:outline focus:outline-2 focus:outline-accent";

export function Empty({ children }: { children: ReactNode }) {
  return <p className="rounded-md border border-dashed border-line p-6 text-center text-sm text-muted">{children}</p>;
}

export function ErrorText({ error }: { error: unknown }) {
  if (!error) return null;
  return <p role="alert" className="text-sm text-bad">{error instanceof Error ? error.message : String(error)}</p>;
}

/** Accessible modal (Radix Dialog: focus trap, Escape, focus restore, scroll lock). */
export function Dialog({ open, title, onClose, children, wide }: { open: boolean; title: string; onClose: () => void; children: ReactNode; wide?: boolean }) {
  return (
    <RD.Root open={open} onOpenChange={(o) => !o && onClose()}>
      <RD.Portal>
        <RD.Overlay className="fixed inset-0 z-50 bg-black/60" />
        <RD.Content aria-describedby={undefined}
          className={`fixed left-1/2 top-10 z-50 max-h-[calc(100vh-5rem)] w-[calc(100%-2rem)] -translate-x-1/2 overflow-y-auto ${wide ? "max-w-4xl" : "max-w-xl"} rounded-lg border border-line bg-panel p-5 text-ink shadow-2xl`}>
          <div className="mb-4 flex items-center justify-between gap-4">
            <RD.Title className="text-lg font-semibold">{title}</RD.Title>
            <RD.Close asChild><Button variant="ghost" aria-label="Close">✕</Button></RD.Close>
          </div>
          {children}
        </RD.Content>
      </RD.Portal>
    </RD.Root>
  );
}

/** Side drawer (Radix Dialog). Used for the agent inspection panel. */
export function Sheet({ open, title, onClose, children }: { open: boolean; title: string; onClose: () => void; children: ReactNode }) {
  return (
    <RD.Root open={open} onOpenChange={(o) => !o && onClose()}>
      <RD.Portal>
        <RD.Overlay className="fixed inset-0 z-50 bg-black/40" />
        <RD.Content aria-describedby={undefined}
          className="fixed inset-y-0 right-0 z-50 w-full max-w-md overflow-y-auto border-l border-line bg-panel p-4 text-ink shadow-2xl">
          <RD.Title className="sr-only">{title}</RD.Title>
          {children}
        </RD.Content>
      </RD.Portal>
    </RD.Root>
  );
}

export function AvatarIcon({ avatar, size = 3, label }: { avatar: Avatar; size?: number; label?: string }) {
  const ref = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const c = ref.current;
    if (!c) return;
    const ctx = c.getContext("2d");
    if (!ctx) return;
    ctx.clearRect(0, 0, c.width, c.height);
    drawFrame(ctx, "stand", avatar, 0, 0, size);
  }, [avatar, size]);
  // Decorative unless labelled: avatars sit next to the agent's name, so they should not be announced twice.
  const a11y = label ? { role: "img", "aria-label": label } : { "aria-hidden": true };
  return <canvas ref={ref} width={CHAR_W * size} height={(CHAR_H - 2) * size} {...a11y}
    className="shrink-0 [image-rendering:pixelated]" />;
}

export function Tabs<T extends string>({ value, onChange, items }: { value: T; onChange: (v: T) => void; items: { id: T; label: ReactNode }[] }) {
  return (
    <div role="tablist" className="flex flex-wrap gap-1 border-b border-line">
      {items.map((i) => (
        <button key={i.id} role="tab" aria-selected={value === i.id} onClick={() => onChange(i.id)}
          className={`-mb-px border-b-2 px-3 py-2 text-sm ${value === i.id ? "border-accent text-ink" : "border-transparent text-muted hover:text-ink"}`}>
          {i.label}
        </button>
      ))}
    </div>
  );
}

export const fmtTime = (iso: string | null | undefined) => (iso ? new Date(iso).toLocaleString() : "—");
