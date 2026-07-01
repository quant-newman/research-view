/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        base: "#0A0E14",
        surface: "#131820",
        elevated: "#1C2430",
        edge: "#232B36",
        primary: "#E4E9F0",
        muted: "#8B95A5",
        dim: "#5A6474",
        up: "#F6465D",   // A股涨=红
        down: "#2EBD85", // A股跌=绿
        accent: "#F0B90B",
        info: "#4A9EFF",
      },
      fontFamily: {
        mono: ["JetBrains Mono", "ui-monospace", "SFMono-Regular", "monospace"],
        sans: ["Inter", "PingFang SC", "Microsoft YaHei", "system-ui", "sans-serif"],
      },
      borderRadius: { DEFAULT: "4px" },
    },
  },
  plugins: [],
};
