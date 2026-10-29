# The millwork bundle

The React side of millwork: the component catalogue (shadcn/ui), the chat
surface, the form renderer, the WebSocket client and the patch store. It is
built once and shipped inside the Python package as
`src/millwork/_bundle/dist`; an app never runs Node.

Only this directory needs Node (pnpm, Node 24). From the repository root:

```
pnpm -C bundle install
pnpm -C bundle exec tsc --noEmit      # types
CI=1 pnpm -C bundle exec vitest run   # unit tests
CI=1 pnpm -C bundle build             # rebuilds src/millwork/_bundle/dist
```

Commit the rebuilt `dist` together with the source change that caused it.

Layout: `src/components/` holds one file per catalogue group, `src/render.tsx`
turns the tree the server sends into React elements, `src/store.ts` applies
patches, `src/ws.ts` keeps the socket and its replay, `src/icons.ts` is the
curated lucide set, `src/custom.tsx` runs an app's own JSX components.
