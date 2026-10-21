# Reviewed daily publication

This procedure publishes the already authorized public Trending/exploration edition to
`byby221b/Dots-Exploration`. It does not create or reschedule automations, change email
recipients/times, send email, or create credentials/services. Email delivery and public
publication are separate operations with separate success states.

## Every fresh execution environment

Never assume that a previous environment's Git settings survived. The environment's
global email may be private or belong to another GitHub account. Configure only this
repository, or explicitly set all four author/committer environment variables for the
commit. Never change global Git settings or account settings as part of publication.
The verified identity is `byby221b <byby221b@users.noreply.github.com>`.

First inspect the private publication ledger for a pending release. Resume that exact
release using the recovery rules below before beginning another one. For a new release,
start from a clean checkout of current main:

```bash
cd /absolute/path/to/Dots-Exploration
# Stop if this is nonempty, including staged and untracked files.
test -z "$(git status --porcelain=v1 --untracked-files=all)" || exit 1
git fetch origin main
release_base=$(git rev-parse origin/main)
git switch --detach "$release_base"
git config --local user.name byby221b
git config --local user.email byby221b@users.noreply.github.com
git config --local user.useConfigOnly true
```

Record `release_base` in the private ledger. Both origin fetch and push must resolve to
this repository; no extra push destinations are allowed. Use the configured connection;
if access is unavailable, stop and report the failure instead of generating credentials.

## Review, import and validate

Materialize only the approved public package through Library's supported transfer flow,
into a directory outside this repository. Inspect its full text, source URLs, actual
image pixels and image metadata. Do not import original email, headers, addresses,
sending logs, personal feedback/projects, private instructions, credentials or audit
files. The review flag in JSON is not a substitute for this review. Preserve original
publication dates, source order, full explanations, pronunciation aids and factual
limitations; do not imply that an unrun experiment or unheard audio was verified.

Use `articles/<id>.json` plus referenced `assets/` as specified in the README. Stable IDs
must not contain private message identifiers. New articles start at revision 1. Revisions
increment by exactly one, keeping ID/date/channel/series fixed; existing image bytes are
immutable, so changed images require new names. Identical reimports must be no-ops.

Before importing, save the current `site/catalog.json` outside the repository as the
batch baseline. Define the expected changed IDs, new image paths and added counts from
the reviewed package, not from an unexplained Git diff. Record this scope privately.

```bash
release_package=/absolute/path/to/reviewed-package
python3 scripts/import_content.py "$release_package"
python3 scripts/generate.py --public
python3 scripts/generate.py --public --check
python3 -m unittest discover -s tests -v
python3 scripts/verify.py
node --check web/app.js
```

If `git status --porcelain=v1 --untracked-files=all` is empty after import/build, do not
create an empty commit. Compare the existing remote content with the reviewed package;
if already deployed, reconcile the private publication state to that existing release.
Do not resend email because the public import was a no-op.

For changed content, run the real-content browser checks with the saved catalog and the
reviewed increment (including zero additions for revisions). Set the four `added_*`
variables from the approved batch; they are not guessed from the observed result:

```bash
python3 tests/pilot_browser_qa.py \
  --output /absolute/path/outside/repo/reading-qa \
  --baseline /absolute/path/outside/repo/baseline-catalog.json \
  --expect-added-articles "$added_articles" --expect-added-images "$added_images" \
  --expect-added-trending "$added_trending" --expect-added-exploration "$added_exploration"
```

Inspect representative desktop and narrow-screen screenshots, tables, formulas and
folded answers. The suite covers the whole catalog at 1440/768/375/320px and no-JavaScript
reading. For presentation-code changes, run `python3 tests/browser_qa.py` as well.

Use normal browser sandboxing and TLS verification. If the local secure browser cannot
start, or a separate managed browser cannot reach this environment's localhost, record
the exact environment failure and defer only real-browser acceptance to the deployed
public URL. Do not disable sandboxing, bypass certificate/proxy/access controls, or
create an unapproved preview deployment. Privacy review, schema/revision validation,
deterministic generation, unit tests, local-link checks, JavaScript checks, reviewed
scope, commit identity and the mandatory prepublish gate still run before push.
An unavailable browser is not a waiver for a known content, static-test or UI defect.
If a browser does run and finds a defect, fix it before publishing. Synthetic browser
regressions for presentation changes still require a secure environment; this fallback
is not permission to skip those regressions.

After all pre-push gates pass, an ordinary authorized push may proceed with browser
acceptance pending. Keep the release `verification_pending` until exact-SHA deployment,
live-file verification and desktop/narrow-screen browser acceptance all succeed.

## One commit, then the mandatory publication gate

Review `git diff --stat`, the complete changed-file list and `git diff --check`. Stage
only the specifically reviewed canonical files/images and the complete regenerated
`site/`. Never use a broad `git add .` that could include unrelated files.

The following example scope is a template: replace the ID and image path with the actual
reviewed values. Repeat `--article-id` for every changed article and `--asset` for every
new image; omit `--asset` for a text-only edition. Unchanged existing references are not
new images. `release_scope` must come from the approved package review.

```bash
release_scope=(--article-id reviewed-stable-id --asset assets/reviewed-stable-id/formula.png)
git add -- content/articles/reviewed-stable-id.json content/assets/reviewed-stable-id/formula.png site
git diff --cached --check
GIT_AUTHOR_NAME=byby221b GIT_AUTHOR_EMAIL=byby221b@users.noreply.github.com \
GIT_COMMITTER_NAME=byby221b GIT_COMMITTER_EMAIL=byby221b@users.noreply.github.com \
  git commit -m "Publish reviewed daily archive edition"
release_sha=$(git rev-parse HEAD)
python3 scripts/prepublish.py --base "$release_base" "${release_scope[@]}" &&
  git push origin HEAD:refs/heads/main
```

The gate is read-only and validates the actual commit's author **and** committer, exactly
one direct child of the recorded base, clean index/worktree/untracked files, exact
canonical change scope, revision rules, immutable/referenced images, safe public content,
full deterministic generation, local links and current remote main. `site/` is allowed
only if it exactly matches regeneration. Recheck immediately before every push attempt.
An ordinary push rejects a main update that races the gate. Never force push for daily
publication, never amend/rewrite published history, and never make an empty probe commit.
The gate is a required runner step, not a server-side branch rule; a direct push that
skips it is not protected by it.

Maintenance is a separate release. Use explicit `--maintenance-path README.md` (repeat
per reviewed script/test/doc/style file) instead of article/image arguments. It cannot
mix canonical content changes, credentials, arbitrary files or workflow configuration
into a maintenance release. No new scheduled workflow or service is required.

## Deployment and private state

After push, confirm `git ls-remote origin refs/heads/main` equals `release_sha`. Find the
workflow run by **that exact SHA**, then wait for both build and Pages deployment success:

```bash
gh run list --repo byby221b/Dots-Exploration --commit "$release_sha" \
  --json databaseId,headSha,status,conclusion,url
gh run watch "$release_run_id" --repo byby221b/Dots-Exploration --exit-status
gh api "repos/byby221b/Dots-Exploration/deployments?sha=$release_sha"
```

Set `release_run_id` from the matching run, not the most recent unrelated run. Check the
matching `github-pages` deployment's latest status. Fetch the live `build-manifest.json`
and compare its SHA-256/bytes against this release's committed manifest, then check the
catalog, affected full articles and images against the listed hashes. A successful push
alone is not a successful publication. Do not bypass proxy, permissions or TLS checks.
If the environment cannot read the live site, record `verification_pending` and provide
the exact commit/manifest/CI evidence for independent verification.

For deferred browser acceptance, use a secure browser environment with a clean checkout
of `release_sha`, after confirming the Actions run and Pages deployment for that SHA.
Do not substitute the latest checkout or an unrelated deployment. Keep evidence outside
the checkout. Run the same real-content suite against the authorized Pages root:

```bash
python3 scripts/generate.py --public --check
python3 tests/pilot_browser_qa.py \
  --base-url https://byby221b.github.io/Dots-Exploration/ \
  --commit "$release_sha" \
  --output /absolute/path/outside/repo/deployed-reading-qa \
  --baseline /absolute/path/outside/repo/baseline-catalog.json \
  --expect-added-articles "$added_articles" --expect-added-images "$added_images" \
  --expect-added-trending "$added_trending" --expect-added-exploration "$added_exploration"
```

The remote mode requires the exact clean local commit and compares the live manifest
and every listed file (catalog, full articles, images, scripts and styles) with that
checkout, both before and after browser checks. It rejects redirects, HTTP errors and
byte mismatches, using normal TLS checks. It runs the same 1440/768/375/320px and
no-JavaScript assertions as local mode. Inspect screenshots as well as the report.
Matching bytes alone cannot identify a code-only maintenance commit; the exact-SHA
Actions and Pages deployment evidence remains mandatory. If another deployment races
verification, stop and reconcile the SHA rather than accepting unrelated results.

If the public URL or secure browser is still unavailable, retain `verification_pending`
and report the failed step; a push or green deployment alone is not `published`.
If deployed acceptance finds a defect, record it and prepare a reviewed ordinary new
fix commit from current main, re-running all applicable gates and deployed acceptance.
Never amend published history or force push. Keep code maintenance and content fixes
in separate releases as required by the gate; do not resend email.

Maintain `sent` and `published` independently in **private Library** using stable edition
ID/revision plus a public-content digest as the idempotency key. Keep delivery receipts,
recipient data and operational failures out of the repository and public Pages. Track:

- Email: pending/sent/failed with its existing delivery receipt; use the established
  email workflow and unchanged approved recipients/time. This repository never sends.
- Publication: pending/committed/pushed/deployed/verification_pending/published/failed,
  including base SHA, target SHA, manifest hash, exact workflow/deployment identifiers
  and the last completed verification step.

If email is already `sent` but publication fails, resume publication only; do not resend.
If public publication succeeds but email fails, retain the successful public state and
let the existing email workflow recover independently. On uncertain push outcome, inspect
remote main first: if it equals the saved target, resume CI/Pages verification. If main
still equals the saved base, re-run the gate on the saved clean commit before retrying
normal push. If main is a different SHA, stop to reconcile the new base and reviewed
package; do not overwrite concurrent work. For CI/deployment failures, inspect the exact
run and retry the failed deployment when appropriate rather than sending mail again.
Do not mark `published` until exact-SHA deployment and live-content verification succeed.
