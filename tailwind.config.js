/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./src/**/*.{html,py,js}",
    "./src/phoresis_ui/templates/**/*.html",
  ],
  darkMode: ["selector", '[data-theme="dark"]'],
  theme: {
    extend: {},
  },
  plugins: [
    require("@tailwindcss/forms"),
    require("@tailwindcss/typography"),
    require("@tailwindcss/container-queries"),
  ],
};
