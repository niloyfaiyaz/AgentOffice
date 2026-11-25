import { useEffect, useRef, useState } from "react";
import { Button } from "../ui";

/** Chat composer: Enter sends, Shift+Enter adds a line, grows with its content. */
export function Composer({ onSend, placeholder, disabled, busy, label = "Message", autoFocus, initial = "", sendLabel = "Send" }: {
  onSend: (text: string) => void; placeholder?: string; disabled?: boolean; busy?: boolean; label?: string;
  autoFocus?: boolean; initial?: string; sendLabel?: string;
}) {
  const [text, setText] = useState(initial);
  const ref = useRef<HTMLTextAreaElement>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 320)}px`;
  }, [text]);
  const send = () => {
    const t = text.trim();
    if (!t || disabled || busy) return;
    onSend(t);
    setText("");
  };
  return (
    <form className="flex items-end gap-2 rounded-lg border border-line bg-bg p-2 focus-within:outline focus-within:outline-2 focus-within:outline-accent"
      onSubmit={(e) => { e.preventDefault(); send(); }}>
      <textarea ref={ref} aria-label={label} rows={1} autoFocus={autoFocus} value={text} placeholder={placeholder} disabled={disabled}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); send(); } }}
        className="min-h-[2.5rem] flex-1 resize-none bg-transparent px-1.5 py-1.5 text-sm text-ink outline-none placeholder:text-muted" />
      <Button variant="primary" disabled={disabled || busy || !text.trim()}>{busy ? "Sending…" : sendLabel}</Button>
    </form>
  );
}
