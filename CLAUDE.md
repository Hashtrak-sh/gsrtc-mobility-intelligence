# Claude Code Entry Instructions

Before editing code, read these files in order:

1. `RULES.md`
2. `docs/PROJECT_BRIEF.md`
3. `docs/ARCHITECTURE.md`
4. `docs/DATA_SCHEMA.md`
5. `docs/ANALYTICS_AND_ALGORITHMS.md`
6. `docs/UX_AND_DEMO.md`
7. `docs/ACCEPTANCE_TESTS.md`

Then read the current milestone prompt under `prompts/`.

## Operating mode

- Act as planner, senior Python developer, test engineer, and careful technical writer.
- Do real implementation: inspect the repository, create/edit files, run commands and tests, fix failures, and report what was actually verified.
- Work one milestone at a time. Do not attempt a shallow whole-app implementation in one pass.
- Before changing a shared schema or public function, explain the proposed change and update the schema documentation and tests in the same change.
- Never claim a feature works unless you ran it or state precisely why it could not be verified.
- At the end of every milestone, provide: files changed, commands run, test results, known limitations, and the exact next prompt/milestone.
- Keep the app runnable at each milestone after the scaffold is complete.
- Prefer small functions, type hints, deterministic calculations, clear error messages, and a clean nontechnical UI.
- Do not add new dependencies without checking whether an existing dependency or simpler method can meet the need.

## First action

Start with `prompts/00_BOOTSTRAP.md`. Do not begin implementing later milestones until the bootstrap output is reviewed and the data contract is documented.
