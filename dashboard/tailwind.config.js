/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        surface: {
          900: "#0f1117",
          800: "#161b27",
          700: "#1e2533",
          600: "#252d3d",
        },
        vectora: {
          black: "#000000",
          green: "#00ff00",
          dim: "#006600",
          mid: "#009900",
          amber: "#ffaa00",
          red: "#ff2200",
          cyan: "#00ffcc",
          white: "#aaffaa",
        },
      },
    },
  },
  plugins: [],
}
