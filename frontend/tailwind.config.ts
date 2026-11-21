import type { Config } from 'tailwindcss'

export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        navy: '#1F3A5F',
        ink: '#253247',
        slate: '#5B6B7F',
        mist: '#F5F7FA',
        line: '#D9E0E8',
        success: '#287A56',
        warning: '#A66A00',
        danger: '#B23A48',
      },
      fontFamily: {
        sans: ['Inter', 'ui-sans-serif', 'system-ui', 'sans-serif'],
      },
    },
  },
  plugins: [],
} satisfies Config
