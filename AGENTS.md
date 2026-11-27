# Project working agreement

- Use Python for the application. The delivery target is an offline Windows
  installer with the required runtime and dependencies bundled.
- Preserve the supplied NCSC branding, original routing-slip template, current
  document flows and existing data during upgrades.
- A shared offline workspace needs a reachable office network and an awake host.
  Independent installations must not be described as automatically synchronized.
- Never commit an office database, accounts, password/recovery material, uploads,
  environment files, virtual environments, dependency wheels or build output.
  Use fictional data and isolated temporary directories for testing.
- Repository: https://github.com/MeAngela-spec/NCSC-RO1_Project.git.
- The owner has authorized committing and pushing requested, checked changes to
  main without asking again. Respect branch protections. Fetch before publishing,
  preserve intervening changes and never force-push to bypass another update.
- When the Git CLI lacks credentials, use the connected GitHub integration for
  authorized repository writes. Do not request passwords or tokens in chat.
- Report the resulting commit, checks and any material limitations. Always supply
  `git pull --ff-only origin main` for the owner's existing local clone.
- Never claim an installer exists until its Windows build has succeeded and a
  downloadable artifact is available. Keep source-only and installer instructions
  clearly distinguished until then.

## Protected login presentation

- The owner froze the login design on 27 November 2026. Future document, printing,
  account-management or dashboard updates MUST NOT change its presentation unless
  the owner explicitly requests a login design change.
- Keep login styles isolated in `assets/login.css`, loaded after `assets/style.css`.
  Preserve the login DOM in `login()` in `assets/app.js`, its official logo and
  geometric background. Nonvisual authentication fixes must preserve these visuals.
- Desktop branding stays together at the upper left: 84 px horizontal / 32 px top
  inset, 72 px seal, 14 px republic text, 19 px agency text, 18 px regional-office text.
  The form is capped at 440 px wide, system title at 48 px, and welcome title at
  32 px. Keep these sizes independent of viewport width. Preserve the blue/white
  panel gradient and responsive narrow-screen rules; never disable browser zoom.
- Before a future change to shared styles, review the login at 1366x768 and a
  narrow viewport to ensure no shared selector changes its size or placement.

## Workspace presentation and controls

- Workspace styling is isolated in `assets/workspace.css` and scoped to
  `body[data-workspace]`; it must not affect the protected login or printed pages.
- `assets/ui.js` enhances native select/date/file fields. Preserve the underlying
  fields, names, values, validation and change/input events used by the application.
  New controls must work with keyboard navigation and reduced-motion preferences.
- Keep all UI assets local so the office LAN workspace needs no internet or CDN.
