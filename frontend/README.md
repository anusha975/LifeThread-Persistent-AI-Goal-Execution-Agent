# LifeThread Frontend

React + TypeScript + Vite + Tailwind CSS client application for the LifeThread platform.

## Development

```bash
# Install dependencies
npm install

# Start development server
npm run dev

# Run TypeScript type check
npm run typecheck

# Build production bundle
npm run build
```

## Architectural Isolation

- Communicates strictly with the Backend REST API (proxied to `http://localhost:8000` in Vite).
- Never accesses database or executes agent logic directly in client code.
