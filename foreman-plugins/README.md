# Foreman use-case shells

Omega's domain tabs in the Foreman control plane. Two of them:

| Directory | Shell | What it is |
| --- | --- | --- |
| `victoria/` | `@omega-foreman/victoria` | The trading desk — six tabs over the Go API on `:8080` (Overview, Runs, Live, Trades, Equity, Signals) |
| `polymarket/` | `@omega-foreman/polymarket` | Prediction markets — one tab, transcribed from `projects/polymarket.yaml`, with **no backend yet** and saying so |

They live here rather than in the harness because they are *omega's* domain
knowledge: the shape of a training run, which node implements which pipeline
step, the fact that `/api/v1/training/progress` 500s because `run_training.py`
writes an array where the handler decodes a struct. None of that is the
harness's business, and every time it drifts, it drifts on this side.

## How they reach a screen

They are **built by the harness**, not by anything in this repo. The harness
(`~/projects/omega/harness`) reads `foreman-plugins.json` at its root:

```json
{ "plugins": ["../foreman-plugins/victoria", "../foreman-plugins/polymarket"] }
```

…resolves those paths at Vite config load, and generates a static import per
plugin. So:

- **Adding a tab is a change here plus one row in the harness's roster test.**
  A new endpoint, a new colour, a rewritten view body — those really are a
  change here and nothing there. But adding or renaming a *view* is not: the
  harness's `roster.test.ts` asserts each shell's exact view ids, so a new tab
  fails it until that list is updated too. The lockstep is deliberate — the
  host is asserting what it actually renders, and a tab appearing or vanishing
  in the operator's UI is precisely the change nobody should be able to make
  silently from another repository.
- **Adding a whole new shell is a change here plus one line in that JSON.**
- **A path in that config that is not on disk fails the harness build**, with
  the absolute path and "clone the repository that provides it" in the message.
  It can never become a blank tab in front of an operator.

The only thing these packages depend on is `@omega-harness/usecase-kit` — the
plugin contract (`UseCaseShell`, `UseCaseViewProps`, `createDataSource`, the
`ObjectiveState` wire types) and its `/ui` entry point (`Panel`, `Pill`,
`SectionLabel`, `StatusDot`, `clock`). It is wired as a `file:` dependency
pointing into the harness checkout, which is what gives editors and `tsc` the
types here. At build time the harness resolves it through a Vite alias to its
own workspace copy, so there is exactly one kit in the bundle.

## Working on them

```bash
# once, or after the kit changes
cd ../harness && pnpm --filter @omega-harness/usecase-kit build && cd -
npm install                 # symlinks the kit, installs react/vitest for the tests

npm run check               # typecheck + tests      (make foreman-plugins-check from the repo root)
npm test                    # tests only
npm run typecheck           # tsc --noEmit
```

To see them in the app, run the harness dev server — `cd ../harness && task dev`
(or `task dev:seed`, which seeds objectives carrying `useCase: victoria` and
`useCase: polymarket` so both tabs are reachable by clicking). **Editing a file
here hot-reloads there**: Vite watches every file in the module graph, wherever
it lives, and Tailwind scans these directories for classes, so a class written
here is generated live. Verified, not assumed.

## The rules, in short

Full detail is in the harness's `docs/USE-CASE-SHELLS.md`. The three that bite:

1. **A shell is a pure export.** The entry module exports exactly one
   `UseCaseShell` object and does nothing else at import time — no
   registration, no fetching. Registering is the host's job.
2. **`UseCaseViewProps` is six fields and never widens.** Domain data comes from
   the shell's own typed client (`createDataSource`), never from the host.
3. **Never render a number you did not get.** Absent is an em dash. An empty
   state, an error state and a no-backend state must look different, because
   they have different fixes and only one of them is the operator's.

## Testing

`npm test` runs vitest with no DOM: views are rendered with
`renderToStaticMarkup` from `react-dom/server`, which gives the text that
reaches the operator without a test environment to carry. Assert **values** —
step ids, colours, formatted strings — not shapes.

What is *not* tested here is registration: that these shells reach the roster,
that their tabs land after the core six, that no core tab is shadowed. Those are
assertions about the harness and live there
(`apps/web/src/foreman/usecases/roster.test.ts`), where they run against the
generated roster rather than against a copy.
