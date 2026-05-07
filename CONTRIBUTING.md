# Contributing to Orion

Thanks for the interest. A few ground rules before you open a PR.

## Developer Certificate of Origin (DCO) — required

Every commit to this repo must be signed off under the
[Developer Certificate of Origin](https://developercertificate.org/). This
is a lightweight legal attestation that you have the right to submit the
code you're contributing. It is **not** a CLA — nothing transfers
copyright. You keep authorship of your code. But the sign-off is what
lets the project stay relicensable and clean for future commercial
paths.

### How to sign off

Add `-s` (or `--signoff`) to every commit:

```bash
git commit -s -m "Your commit message"
```

Git appends a `Signed-off-by: Your Name <you@example.com>` trailer to
the commit message. That trailer is the sign-off. You can also type it
by hand if you prefer.

### Set your git identity correctly first

```bash
git config --global user.name "Your Real Name"
git config --global user.email "you@example.com"
```

The name and email on `Signed-off-by` must match `user.name` /
`user.email`.

### Forgot to sign off?

Rebase and amend — interactively is easiest:

```bash
git rebase --signoff HEAD~N       # N = number of commits to fix
git push --force-with-lease       # only on your fork / feature branch
```

CI will block the PR until every commit in the branch carries a valid
sign-off.

## What we accept

- **Bug fixes** with a reproducible case and either a test or a clear
  "before / after" snippet.
- **Small, focused features** that line up with the roadmap in
  [`README.md`](README.md). Open an issue first for anything non-trivial
  — it saves you writing code we'd have to redesign.
- **Docs improvements** — typos, unclear paragraphs, missing examples,
  platform-specific gotchas. Low-friction wins.

## What we don't accept (yet)

- Sweeping refactors. The brain is still small enough (~200 LOC in the
  core) that a rewrite destroys more context than it creates.
- Framework dependencies. Orion is explicitly zero-framework. If a PR
  adds LangChain / LlamaIndex / Haystack / similar, it will be closed.
- Vendored SDKs. The fuel layer deliberately stays thin — one adapter
  per tool, no vendor SDK shims.

## Local checks before you push

```bash
python orion_preflight.py        # all green
python tests/run_all.py          # all scenarios green
```

Both should pass cleanly on your machine. If preflight surfaces a yellow
row, it's a warning not a blocker — but mention it in the PR.

## Questions

Open a GitHub issue. Keep it short: what you tried, what happened, what
you expected. Screenshots or preflight output help.
