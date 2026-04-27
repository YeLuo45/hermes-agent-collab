/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        primary: {
          50: "#f0f4ff",
          100: "#e0e8ff",
          200: "#c7d4ff",
          300: "#a3b8ff",
          400: "#7a91ff",
          500: "#5865f2",
          600: "#4752c4",
          700: "#3c45a5",
          800: "#333c86",
          900: "#2d3468",
        },
        dark: {
          100: "#2a2d3a",
          200: "#242736",
          300: "#1e2130",
          400: "#181b28",
          500: "#12151f",
        },
      },
      animation: {
        bounce: 'bounce 0.5s ease-in-out',
        shake: 'shake 0.3s ease-in-out',
        fadeIn: 'fadeIn 0.3s ease-out forwards',
        pop: 'pop 0.3s ease-out',
        wiggle: 'wiggle 0.5s ease-in-out',
      },
      keyframes: {
        bounce: {
          '0%, 100%': { transform: 'scale(1)' },
          '50%': { transform: 'scale(1.15)' },
        },
        shake: {
          '0%, 100%': { transform: 'translateX(0)' },
          '25%': { transform: 'translateX(-8px)' },
          '75%': { transform: 'translateX(8px)' },
        },
        fadeIn: {
          '0%': { opacity: '0', transform: 'scale(0.8)' },
          '100%': { opacity: '1', transform: 'scale(1)' },
        },
        pop: {
          '0%': { transform: 'scale(0)' },
          '80%': { transform: 'scale(1.1)' },
          '100%': { transform: 'scale(1)' },
        },
        wiggle: {
          '0%, 100%': { transform: 'rotate(-3deg)' },
          '50%': { transform: 'rotate(3deg)' },
        },
      },
    },
  },
  plugins: [],
};
