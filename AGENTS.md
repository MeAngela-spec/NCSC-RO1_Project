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
