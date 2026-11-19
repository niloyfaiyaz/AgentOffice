/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bg: "var(--bg)", panel: "var(--panel)", panel2: "var(--panel-2)", line: "var(--line)",
        ink: "var(--ink)", muted: "var(--muted)", accent: "var(--accent)", accentInk: "var(--accent-ink)",
        ok: "var(--ok)", warn: "var(--warn)", bad: "var(--bad)", info: "var(--info)",
      },
      fontFamily: { mono: ["ui-monospace", "SFMono-Regular", "Menlo", "monospace"] },
    },
  },
  plugins: [],
};
