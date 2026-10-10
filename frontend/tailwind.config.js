/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // All colors are driven by CSS variables so a single data-theme switch
        // re-themes the whole app (incl. React Flow nodes and charts).
        bg: "var(--bg)",
        panel: "var(--panel)",
        panel2: "var(--panel-2)",
        panel3: "var(--panel-3)",
        "panel-2": "var(--panel-2)",
        "panel-3": "var(--panel-3)",
        line: "var(--line)",
        line2: "var(--line-2)",
        "line-2": "var(--line-2)",
        ink: "var(--ink)",
        muted: "var(--muted)",
        faint: "var(--faint)",
        accent: "var(--accent)",
        accentfg: "var(--accent-fg)",
        ok: "var(--ok)",
        warn: "var(--warn)",
        err: "var(--err)",
      },
      fontFamily: {
        sans: ["Inter", "ui-sans-serif", "system-ui", "sans-serif"],
        mono: ["'JetBrains Mono'", "ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
      fontSize: {
        "2xs": ["0.6875rem", { lineHeight: "1rem" }],
      },
      borderRadius: {
        md: "0.5rem",
        lg: "0.625rem",
        xl: "0.875rem",
      },
      boxShadow: {
        panel: "0 1px 2px rgba(0,0,0,0.25), 0 8px 24px -16px rgba(0,0,0,0.5)",
        pop: "0 10px 40px -12px rgba(0,0,0,0.55)",
      },
      keyframes: {
        "fade-in": { from: { opacity: "0" }, to: { opacity: "1" } },
        "slide-up": {
          from: { opacity: "0", transform: "translateY(6px)" },
          to: { opacity: "1", transform: "translateY(0)" },
        },
        pop: {
          "0%": { transform: "scale(0.96)", opacity: "0" },
          "60%": { transform: "scale(1.02)" },
          "100%": { transform: "scale(1)", opacity: "1" },
        },
        "bar-grow": { from: { transform: "scaleY(0)" }, to: { transform: "scaleY(1)" } },
      },
      animation: {
        "fade-in": "fade-in 0.18s ease-out",
        "slide-up": "slide-up 0.22s cubic-bezier(0.22,1,0.36,1)",
        pop: "pop 0.2s cubic-bezier(0.22,1,0.36,1)",
      },
    },
  },
  plugins: [],
};
