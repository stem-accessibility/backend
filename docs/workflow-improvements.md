# Workflow improvements

Draft of 2026-11-20. Covers both repositories, this backend and the
[frontend](https://github.com/stem-accessibility/frontend). Edit freely.

Many people now contribute to both repositories at once. These recommendations come from
reviewing every open pull request in both (16 at the time of writing). Each one names the
problem it would have prevented. Most are small; the list is in order of payoff.

## Summary

| # | Change | Problem it fixes | How | Effort |
|---|---|---|---|---|
| 1 | CI on `main`, then protect `main` | PRs inherit failures from `main`; no checks run on fork PRs | Merge the CI PRs; repository settings | Small |
| 2 | Changelog fragments | Every PR conflicts in `CHANGELOG.md` | A PR adding `changelog.d/` and a script | Small |
| 3 | `CONTRIBUTING.md` and a PR template | Rules live in reviewers' heads; stacked PRs from forks | A PR per repository | Small |
| 4 | `CODEOWNERS` | Review falls on one person | A PR, once owners are named | Small |
| 5 | Issues before non-trivial work | Two people fixed the same thing | Habit, labels, issue templates | Small |
| 6 | Migration rules and a heads check | An applied migration was edited; parallel PRs can add the same revision | A PR adding a CI step | Small |
| 7 | Automate the accessibility checks reviewers repeat | The same review comments on many PRs | A PR running axe and the contrast test in CI | Medium |
| 8 | One canonical pair of repositories | Repository descriptions still say "snapshot from …" | Maintainer decision | Small |
| 9 | Rules for AI-assisted PRs | Large multi-concern PRs | Habit and a label | Small |
| 10 | Private security reports | Security problems discussed in public | Repository settings, `SECURITY.md` | Small |
| 11 | Dependency updates and releases | Stale lockfile, no release tags | Dependabot, tags | Small |

## Now: merging the open pull requests

Merging in this order keeps conflicts small and lets later PRs get green checks:

1. **frontend#7** (lockfile, lint to 0 errors, CI) and **backend#6** (worker import, CI). Every
   other PR's checks depend on these.
2. **frontend#6** (contrast). The axe results in other PRs assume it.
3. The small independent ones: **frontend#13–#17** and **frontend#10**.
4. **frontend#9**, then **frontend#11**. They are stacked on #7. Once #7 is merged their diffs
   shrink to their own commits.
5. The roadmaps last, since they describe the others: **frontend#12** and **backend#7**.
6. The slide-deck pair **frontend#5** and **backend#5** together, once their review items are
   addressed.

Until changelog fragments exist (section 2), expect a small conflict in `CHANGELOG.md` on each PR
after the first. Keep both sides' entries.

## 1. CI on `main`, then protect `main`

**What we saw.** On the frontend, `main` had 179 lint errors and a `package-lock.json` out of step
with `package.json`, so `npm ci` failed. Every pull request inherited those failures, and
contributors could not tell their own errors from old ones. Neither repository ran any checks:
there was no `.github/` folder. Vercel previews on fork PRs wait for a team member to authorize
each one.

**Do:**

- Merge the CI pull requests (frontend#7, backend#6).
- Add a branch ruleset for `main` in both repositories:
  - changes arrive through pull requests;
  - the CI job must pass (`check` in the frontend, `test` in the backend);
  - one approving review is required;
  - force pushes and deletion are blocked.
- Leave "require branches to be up to date" off for now. With this many parallel PRs it forces a
  rebase after every merge. If the volume keeps growing, GitHub's merge queue does the same job
  without the churn.
- Settings → Actions → General: choose "Require approval for first-time contributors". With
  "Require approval for all outside collaborators", regular contributors' PRs wait for a
  maintainer before CI runs.
- Vercel: decide whether regular contributors join the Vercel team, or a maintainer authorizes
  preview deploys on fork PRs. Today previews silently wait.
- Use squash merging by default. Small PRs become one commit each on `main`, and the PR
  description becomes the commit message.

## 2. Changelog fragments

**What we saw.** Both changelogs are a single file with an "Unreleased" section. Every PR adds its
lines at the top of the same subsection. Frontend#7, #9, #10, #11 and #13–#17 all touch the same
lines, so after the first merge every other one conflicts.

**Options:**

| Option | How it works | Trade-off |
|---|---|---|
| **(a) Fragments** (recommended) | Each PR adds `changelog.d/<PR number>.<type>.md` (type: `added`, `changed`, `fixed`, `removed`, `security`) holding its bullet lines. At release a script moves them into `CHANGELOG.md` under the version heading and deletes the files. | Authors still write the entry, and files never collide. Needs a short script. |
| (b) Generated from PR titles and labels | A release tool (e.g. release-drafter) builds the notes from merged PRs. | Least work, but entries are one line each and lose detail, such as the backend's "migration to run before deploying". |
| (c) Only the merger edits `CHANGELOG.md` | Authors put the entry in the PR description; whoever merges copies it in. | No conflicts, but more work for the few people who merge. |

With (a), a CI step can require a fragment unless the PR carries a `no-changelog` label
(documentation, tests). The backend's rule that a database change names its migration stays: it
goes in the fragment.

## 3. `CONTRIBUTING.md` and a PR template

**What we saw.** Contributors already use the same informal PR layout (Summary, Testing,
Accessibility check). The other rules exist only in reviewers' comments.

**Do.** Add to each repository:

- `CONTRIBUTING.md`, covering:
  - setup, and how to run lint, tests and the build (the commands CI runs);
  - the PR rules below;
  - where to ask questions.
- `.github/pull_request_template.md` with these headings:
  - **Summary**: what changed for users, and why.
  - **Testing**: commands run and their results.
  - **Accessibility check**: keyboard, screen reader, braille or contrast as relevant. Say "not
    checked" where it wasn't.
  - **Database** (backend): the migration, if any, and whether to run it before deploying.
  - **Related pull requests**: the paired frontend or backend PR.

**Rules for pull requests:**

- **One concern per PR.** Frontend#13–#17 are the model: each fixes one thing and is easy to
  review. The slide-deck PRs combine detection, cropping, the reader, publishing and the editor
  flow, which makes review slow and lets problems through.
- **Link paired PRs both ways.** Frontend#5 and backend#5 need each other, but only the code says
  so.
- **Stacked PRs.** GitHub cannot base a PR on a branch in someone's fork. So stacked work from
  forks targets `main` and repeats its parents' commits (frontend#9 showed #7's commit; #11
  showed both). Either avoid stacks, or give regular contributors write access so they can push
  branches to the organization's repository and base each PR on the previous branch.
- Don't push to someone else's PR branch without asking. Suggest changes in a review instead.

## 4. `CODEOWNERS`

**What we saw.** Almost every commit on `main` in the history we looked at has the same author.
In this round, every review that requested changes came from one maintainer.

**Do.** Add `.github/CODEOWNERS` so GitHub requests the right reviewer automatically. Owners must
be people or teams with write access. A starting point, with owners still to be named:

```
# frontend
/src/braille/            OWNER_TBD
/src/math/               OWNER_TBD
/src/sonification/       OWNER_TBD
/src/components/charts/  OWNER_TBD
/src/arboretum/          OWNER_TBD
/vendor/                 OWNER_TBD

# backend
/migrations/             OWNER_TBD
/backend/pipeline/       OWNER_TBD
/backend/routes/         OWNER_TBD
/backend/jobs/           OWNER_TBD
```

## 5. Issues before non-trivial work

**What we saw.** Color contrast was worked on twice: a branch in one contributor's fork and
frontend#6.

**Do:**

- Before starting anything bigger than a small fix, open an issue or claim an existing one with a
  comment.
- Labels: `accessibility`, `braille`, `math`, `charts`, `backend-contract` (needs a matching PR
  in the other repository), `good first issue`, `needs decision`.
- Issue templates: bug, accessibility barrier (who is affected, assistive technology, steps) and
  feature request.
- Optionally, a project board across both repositories.

## 6. Backend database migrations

**What we saw:**

- Migration names mix numbers (`0001`–`0007`) and Alembic hashes (`b7d2e4f19a60`,
  `ee8798c827c8`).
- Backend#5 edits `b7d2e4f19a60`, which databases have already run, so the change only reaches
  fresh databases.
- Two open PRs that each add `0008` would both pass review and fail only at deploy.

**Do:**

- Rule: never edit a migration that has been merged. Add a new one.
- Name new migrations `NNNN_short_description.py` with the next free number.
- In CI:
  - `flask db heads` must print exactly one head, which catches two PRs adding the same revision;
  - run `upgrade` then `downgrade` on SQLite.
- Keep the existing rule that every new table enables row-level security in its own migration.

## 7. Automate the accessibility checks reviewers repeat

**What we saw.** The same comments came up on many PRs:

- live regions and `role="alert"` for status and errors (frontend#9, #10, #14);
- visible focus rings (#9);
- contrast (#6);
- focusable content inside `aria-hidden` (#16).

The frontend already has an axe script (`e2e/a11y.mjs`), and #6 adds a contrast test
(`e2e/contrast.mjs`). Neither runs in CI. Both default to Chrome at a macOS path; `a11y.mjs`
reads `CHROME_PATH` to override it, but `contrast.mjs` does not.

**Do:**

- Run axe in CI against a production build with the backend mocked. Playwright can answer API
  calls with fixtures, which is how the reviews in this round checked pages. Fail on new serious
  or critical violations.
- In CI, point the scripts at the runner's browser through `CHROME_PATH` (or use Playwright's
  bundled Chromium). Give `contrast.mjs` the same override.
- Add the contrast test to CI once #6 is merged.
- Use component tests (Testing Library, already installed) for the patterns reviewers keep
  checking: status messages in `role="status"`, failures in `role="alert"`, focus kept after an
  action.
- Consider `eslint-plugin-jsx-a11y` for the cheap static checks.

Automated checks don't replace testing with people. Screen reader, braille display and
transcriber review stay in the roadmap, but reviewers can then spend their time on design and
behavior.

## 8. One canonical pair of repositories

The repository descriptions say "snapshot from stem-accessibility/flowchart-accessibility" and
"snapshot from stem-accessibility/grafari". If those repositories still accept changes, work will
split between them.

**Do:**

- Decide which pair is canonical.
- Archive the others, or point their READMEs here.
- Update the descriptions.

## 9. AI-assisted contributions

**What we saw.** Some PRs in this round were written with an AI assistant. Some were large: the
braille PR alone added about 2,200 lines. Reviews found real bugs in them that their own tests
missed, for example the arrowhead rule in the tactile graphic and the `$` parser for math.

**Do:**

- Label these PRs (e.g. `ai-assisted`) and hold them to the same review bar.
- A named person is responsible for each PR and answers review comments.
- Keep them small, under the same one-concern rule.
- Say plainly what was checked by hand and what was not, e.g. "not tested with a screen reader".

## 10. Private security reports

**What we saw.** The review of backend#5 found a denial-of-service: a crafted PDF of a few KB can
crash the worker. It was discussed in a public PR comment. That is fine for code not yet merged,
but problems in deployed code should be reported privately.

**Do:**

- Turn on GitHub's private vulnerability reporting in both repositories.
- Add a short `SECURITY.md` saying how to report a problem and who responds.

## 11. Dependency updates and releases

- Dependabot, weekly and grouped, for npm, pip and GitHub Actions. The frontend lockfile had
  drifted far enough that `npm ci` failed.
- Tag releases. The frontend changelog already names "the matching backend release" for contract
  changes, so a tag per release gives that reference something to point at.

## Decisions needed

1. Changelog approach: (a) fragments, (b) generated, or (c) merger edits. Recommendation: (a).
2. Owners for each area in `CODEOWNERS`.
3. Branch ruleset settings, and who can merge (needs an organization admin).
4. Which repositories are canonical (section 8).
5. Whether regular contributors get write access. That makes stacked PRs and branch previews
   possible.

## What this pull request does

Documentation only. Sections 1, 8, 10 and the Actions and Vercel settings are repository settings
that need an admin. Sections 2–4, 6 and 7 can each follow as a small PR once the decisions above
are made.
