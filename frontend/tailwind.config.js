/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // 5-band analytical label palette (never colour alone — always with text + icon)
        band: {
          "strong-bearish": "#b42318",
          bearish: "#dc6803",
          neutral: "#475467",
          bullish: "#3538cd",
          "strong-bullish": "#067647",
        },
      },
      fontFamily: {
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
    },
  },
  plugins: [],
};
