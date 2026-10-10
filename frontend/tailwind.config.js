/** @type {import('tailwindcss').Config} */
export default {
  darkMode: "class",
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        brand: {
          50: "#eef6ff", 100: "#d9ebff", 200: "#b6d6ff", 300: "#86baff",
          400: "#4d94ff", 500: "#1f6feb", 600: "#1358cc", 700: "#1046a3",
          800: "#123c85", 900: "#14356b",
        },
      },
      fontFamily: {
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "Consolas", "monospace"],
      },
    },
  },
  plugins: [],
};
