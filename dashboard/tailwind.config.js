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
      },
    },
  },
  plugins: [],
}
