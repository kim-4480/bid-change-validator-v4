# Zone Guard and browser CI

Feature PRs that touch more than one owned source-code zone fail the Zone
Guard by default. The cross-zone-approved PR label is the explicit exception
for cross-cutting changes. A maintainer must inspect ownership and reason
before adding that label; this GitHub Action itself cannot enforce who is
allowed to add labels. Configure branch protection, required checks and
review approval separately at the repository level.

Zones: web, api, llm, contracts, db, infra. Docs-only changes are neutral.
The deploy/aws and .github paths belong to infra. Backend Copilot and
Document RAG paths belong to llm.

The existing Playwright suite uses mocked API responses. Running it on CI
validates frontend routes and contract assumptions; it does not validate
live AWS authenticated end-to-end behavior. Live tests must be separately
run against production-safe accounts and data.

Do not bypass required CI by force-merging. No PR is merged automatically.