# KSP CIAP — Frontend (Vite + React)

Runnable Vite project scaffolded around the existing `CIAP_Dashboard.jsx`.
That file is untouched from the version you already have — nothing in it
was rewritten or simplified.

## Setup

```bash
npm install
npm run dev
```

Open the URL Vite prints (default `http://localhost:5173`).

Build for production:

```bash
npm run build
npm run preview
```

## What's here

```
index.html              Vite entry HTML, loads src/main.jsx
package.json             Dependencies + dev/build/preview scripts
vite.config.js           Vite + @vitejs/plugin-react
tailwind.config.js       Content-scans index.html + src/**/*.{js,jsx}
postcss.config.js        tailwindcss + autoprefixer
src/
  main.jsx               ReactDOM root, mounts <App />, imports index.css
  App.jsx                Thin wrapper that renders <CIAPDashboard />
  index.css              @tailwind base/components/utilities
  CIAP_Dashboard.jsx     Your existing dashboard, byte-for-byte unchanged
```

## Dependencies installed

- `react`, `react-dom` — required by the dashboard's hooks and render tree
- `recharts` — used for the AreaChart/BarChart in the Predictive Risk tab
- `lucide-react` — icon set used throughout the sidebar/header
- `tailwindcss`, `postcss`, `autoprefixer` — the dashboard is styled entirely
  with Tailwind utility classes, including arbitrary values like
  `bg-[#0B0F14]`, which Tailwind v3's JIT engine handles natively
- `vite`, `@vitejs/plugin-react` — dev server + build tooling

## A note on verification

This sandbox has no network access to the npm registry, so `npm install`
could not be executed here to prove it end-to-end. What was verified
instead, using a bundler already present in this environment:

- Every file's JSX/JS syntax parses cleanly
- Every import in every file (`react`, `react-dom/client`, `recharts`,
  `lucide-react`, `./App.jsx`, `./CIAP_Dashboard.jsx`, `./index.css`)
  resolves correctly against the dependency names declared in
  `package.json` — the whole module graph bundles with no resolution
  errors

That covers the class of mistakes most likely to break `npm install` /
`npm run dev` (typos in import paths, missing dependencies, syntax errors).
It does not substitute for actually running it — please run
`npm install && npm run dev` locally as the final check.
