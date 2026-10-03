# Harness Engineering

**English** · [한국어](README.md)

[![CI](https://github.com/bean-baek/harness_project/actions/workflows/ci.yml/badge.svg)](https://github.com/bean-baek/harness_project/actions/workflows/ci.yml)

> **A project about how to *operate* autonomous coding agents — not how to *run* them.**

Getting an LLM agent to write code is easy. The hard part is **making its output
trustworthy while nobody is watching.** This repository implements the apparatus
(the harness) that produces that trust, and records every way that apparatus has broken.

---

## 1. What the deliverable is, and what it is not

| | |
|---|---|
| **Is the deliverable** | `harness/` — the operating layer that runs, verifies, measures, and halts the agent |
| **Is the deliverable** | `troubleshooting/` — failure modes that actually occurred, with reproduction, cause, fix, and verification ([list](troubleshooting/INDEX.md), [count](docs/status.md)) |
| **Is NOT the deliverable** | `web_target/` — a todo app. The **test subject** and benchmark task for the harness |

The 75 features in `web_target` (`features.json`) are not the goal; they are the
**measuring instrument.** Defects in the test subject are fixed selectively, filtered by
one question: **"does this failure teach the harness anything?"** (§8)

### Design principle — five refusals to trust

1. **Don't trust self-reports.** "I implemented it" is not evidence. A completion flag is
   recorded only after a tool has run the tests and proven it (TS-006).
2. **Don't trust a green suite.** All tests passing is still not evidence for *that feature.*
   A passing test that cites the feature ID is required (TS-008).
3. **Don't trust unit tests.** If a test supplies the structure it is verifying, that
   structure goes unverified. F-005 passed the gate while the app had no such route (TS-013).
4. **Don't blame the task for infrastructure failures.** Quota exhaustion and auth failures
   are not the feature's fault, so they consume no attempt and abort the whole run (TS-005).
5. **Irreversible actions require a human.** Tools carry three permission tiers, and
   `IRREVERSIBLE` halts the graph to wait for approval.

### Directory layout

```
harness/              the operating layer — gate, measurement, runner, inspection (the deliverable)
  verify.py           evidence gate policy (single owner)
  runner.py           everything tied to an ecosystem — jest, vitest, pytest
  project.py          .harness.json declaration + project inspection
  inspect.py          objective metric (invariant) extraction
  independence.py     evidence independence — does a test supply its own structure
  deadcode.py         self-audit — dead config, orphan code
  tags.py metrics.py mutate.py cli.py
  graph.py router.py state.py tools.py prompts.py memory.py llm_errors.py
  nodes/agents.py     the 5 agent nodes (paid path)
verification/         regression checks — one script per failure mode
troubleshooting/      failure-mode records + evidence/ primary sources
web_target/           the test-subject todo app (not the deliverable)
.harness_memory/      Reflexion primary data — cannot be regenerated, kept
docs/ scripts/ .claude/skills/harness/
config.py exit_codes.py main.py night_shift.py
```

Run the regression checks **from the repo root** — some of them reference `web_target`
by relative path ([verification/README.md](verification/README.md)).

---

## 2. Two execution modes

| | Tokenless mode (recommended) | Paid API mode |
|---|---|---|
| Reasoning engine | **Claude Code session** (covered by subscription) | Gemini API (metered) |
| Enforcement | `python -m harness.cli` (deterministic) | same gate + LangGraph router |
| Unattended | No — a human must open a session | **Yes** (`night_shift.py`, 30-min timeout) |
| Dependencies | stdlib + jest | langchain, langgraph, API key |
| Verification | regression scripts + real jest ([counts](docs/status.md)) | **smoke checks** (stubbed LLM, zero tokens — TS-018) |

**Why the split**: counting the code by character, the deterministic machinery
(gate, measurement, tag linter, tools, CLI) is **2,703 lines** that spend no tokens at all,
while only **2,357 lines** exist to drive the paid API.
**The valuable half was already free** (TS-010 — measured at 2,060 lines then; it grew as
measurement and linting were added).

**The paid path really did run, and is now verified**: `.harness_memory/` holds 67 Reflexion
artifacts dated 2026-04-14, and TS-004/005/007 were failures discoverable only by running it.
But for the six months after that, no test exercised that path — measured by coverage,
`graph.py`·`router.py`·`agents.py`·`memory.py` executed **4 lines of actual logic out of 359**
— and TS-017's refactor proceeded blind on top of it. `repro_ts018.py` removes that blind spot
by stubbing the LLM and driving the graph end to end, and **immediately found two real bugs**
(§11, TS-018).

**Why not move everything to Markdown**: Markdown can only **advise.** When "run the tests
first" was a docstring recommendation, the agent ignored it and graded itself — and
discrimination measurement showed that **any of the 75 features** could have been recorded as
passing. So: **procedure in documents, judgment in code.**

---

## 3. Install

```bash
pip install -r requirements.txt          # harness (for paid mode; tokenless mode needs only stdlib)
cd web_target && npm install && cd ..    # target app
# paid mode only: GOOGLE_API_KEY=... in .env (never commit — it is in .gitignore)

bash scripts/init.sh --install           # all of the above at once
```

---

## 4. Using tokenless mode

```bash
python -m harness.cli next           # next unimplemented feature spec + tag convention
python -m harness.cli show F-006     # one feature's spec and its recorded evidence
python -m harness.cli verify F-006   # gate verdict only (does not touch the flag)
python -m harness.cli mark F-006     # record as passing ONLY if the gate agrees  (0 pass / 1 reject / 2 input error)
python -m harness.cli unmark F-006   # revert to incomplete (removes evidence)
python -m harness.cli audit          # re-verify every passing flag
python -m harness.cli tags           # check that tags point at the right feature
python -m harness.cli mutate F-005   # measure whether the evidence actually bites (slow; not a gate)
python -m harness.cli report         # discrimination + gate-verdict aggregation + run log
python -m harness.cli init           # inspect the project → generate .harness.json (TS-017)
python -m harness.cli inspect        # extract objective metrics, separate what needs human intent
python -m harness.cli deadcode       # self-audit — dead config, orphan code (TS-019)
python -m harness.cli independence   # evidence independence — does a test supply its own structure (TS-020)
python -m harness.cli status         # generate live measurements into docs/status.md (TS-024)
```

`verify` / `mark` / `unmark` append a record to `harness_runtime.log` on every verdict
(`--log` changes the path, `--no-log` disables it). That record is the input to §6.

In a Claude Code session, [.claude/skills/harness/SKILL.md](.claude/skills/harness/SKILL.md)
drives the procedure — four refusals → implement → tagged tests → gate → self-assessment → record.
`--project` works either before or after the subcommand.

### 4.1 A completion flag requires evidence

`mark` makes **the tool itself run the whole suite**, and writes the flag only if all
conditions hold:

1. Zero failing tests in the suite — you did not break another feature
2. **At least one passing test whose name contains this feature's ID**
3. **That tagged test executes at least one line of non-test source** (TS-016)

Without #3, `test('F-006: x', () => expect(true).toBe(true))` counts as perfect evidence —
verified by actually planting it and watching it pass.

The gate does not ask where the evidence *came from* — all three conditions are satisfied
by a single unit test the implementer wrote. That outer shell is reported by
`cli independence` (§4.5, TS-020).

**Tag convention** — not a new rule; it is what `LoginForm.test.tsx` was already doing:

```ts
describe('F-005: unauthenticated user is redirected away from protected pages', ...)  // feature tag
test('F-005.3: the original URL is preserved in ?redirect=', ...)                     // step tag
```

On success, **what justified the pass** is recorded alongside it in `features.json`:

```json
"verification": {
  "verified_at": "2026-10-02T...", "verified_by": "update_features/jest",
  "level": "feature", "suite": { "total": 51, "passed": 51, "failed": 0 },
  "summary": "suite 51/51 passed | tagged 24 passed | steps 3/3 covered",
  "evidence_tests": ["F-005: ... F-005.3: the original URL is preserved", "..."],
  "steps_covered": [1, 2, 3]
}
```

- The test path is **pinned to `"."` by the tool** — you cannot cherry-pick easy tests to fake a pass.
- Strictness: `HARNESS_EVIDENCE_LEVEL` = `suite` / `feature` (default) / `step`.
  Step coverage is **measured and recorded at every level**, enforced only at `step`.
- Only the operator can turn it off: `HARNESS_REQUIRE_TEST_EVIDENCE=false`,
  `HARNESS_REQUIRE_EVIDENCE_COVERAGE=false` (debugging only).
- The source files the evidence executed are recorded as `evidence_sources` —
  e.g. F-005 → `ProtectedRoute.tsx (17)`, `LoginForm.tsx (13)`, making attribution visible.

### 4.2 Does the evidence actually bite — mutation measurement (TS-016)

```bash
python -m harness.cli mutate F-005
```

Coverage only guarantees "the source was executed." A test that executes code while asserting
nothing still passes. The only way to ask the real question is to **inject a defect on purpose.**

Syntax-preserving mutations (invert comparisons, invert logic, neutralize conditions, …) are
applied to the implementation, validated with `tsc`, and the tagged tests are checked for
failure. The original is always restored in a `finally` block.

**It can be a gate (off by default, TS-021).** Setting
`HARNESS_REQUIRE_MUTATION_EVIDENCE=true` makes `mark` require **at least one killed mutant.**
That is a minimum of the same shape as TS-016's "at least one statement executed," not a
ratio — mutation targets are chosen by coverage, so files owned by other features get mixed
in, and applying a percentage to that mixture produces an ungrounded constant like
`EVAL_WEIGHTS`.

Three cases are distinguished: the tool failing to run is a **rejection** (a failed
measurement is not a pass), **no mutable construct** is recorded without rejecting (absence of
a measurement *target* differs from measurement *failure*), and zero kills is a **rejection**.

It is off by default because of cost — `mark` goes from 11s to **42s** (measured).

**Cost, measured warm** — measuring cold is off by 10x:

| Step | Cold | Warm |
|---|---|---|
| `tsc --noEmit` | 10.8s | **1.9s** |
| scoped jest | 18.4s | **2.8s** |

jest runs **first**, and tsc only when jest fails — a mutant that passes compiled, so its
validity needs no second question. Saves 1.9s per surviving mutant.

**The operators were destroying syntax (TS-021).** The `>` → `>=` rule matched **190 sites**
and only **3** were real comparisons — the rest were JSX (108) and generics (32), so
`React.FC<Props>` became `React.FC<Props>=`. `if (X)` → `if (false)` broke on nested parens,
producing `if (false))`. The mutations were testing **the compiler, not the tests**, and the
"discarded" tally hid that fact.

**Detection reach was blocked in two places too (TS-022).**

Sampling was **pinned to the top of each file** — only `lines[0]` per rule.
`LoginForm.tsx` has 19 mutation sites, **all on executed lines**, yet only 3 were attempted;
line 32 always won, so lines 55–56 — `safeRedirectTarget`'s open-redirect guard, i.e.
**TS-011's fix** — were never tested. Overall reach was 23 of 59 sites (39%).

`select_spread()` now gathers every candidate and picks at **even intervals** (not randomly:
reproducibility is what lets a regression pin it). Budget 3 → `[0, 9, 18]`.

The operators **could not touch array declarations.** `routes.ts` has 6 lines executed by
the evidence and **zero** mutation sites — arrays contain no comparisons, logic, or
conditions. So there was no way to inject **the TS-013 bug shape**. Measured by hand:

| Member removed | Result | Suite |
|---|---|---|
| `/` | **survived** | 49 passed / 0 failed |
| `/dashboard` | killed | 48 passed / 1 failed |
| `/profile` | **survived** | 49 passed / 0 failed |
| `/settings` | **survived** | 49 passed / 0 failed |

**Three of four protected paths can be deleted and everything still passes** —
`test.each(PROTECTED_PATHS)` simply **runs fewer tests** when the list shrinks. Meanwhile all
four ladder rungs (tag, coverage, independence, mutation) **pass.**

The `drop_member()` operator closes that hole, reusing the "single-source collections" that
`independence` already locates — the two modules compose to inject **declaration defects.**

**The `types` status** — removing `/dashboard` was first classified as "discarded." But
`drop_member` preserves the array literal, so the syntax is **valid by construction.** tsc
failed because `Record<ProtectedPath, …>` ties the list to its consumer at the type level —
that is **type-level detection.** It is excluded from the evidence score's numerator (what
caught it was not a test) but not buried as "discarded" (that would erase the fact that
structural protection exists).

**Sample size is printed with the number**: `16 of 27 candidates attempted`. Without it,
"33%" gives no way to know how many samples it rests on. Raise it with `--max-per-file` /
`--max-collection`.

After the fix, F-005 scores **33%** (killed 5 / survived 10 / discarded 0 / caught-by-types 1)
over 16 of 27 candidates. The score going *down* is the improvement — the 40% from 3 samples
was an **overestimate** biased to the top of the file, and widening from 10 to 16 samples
holds at 33%.

**I read those survivors as "the test is weak" and nearly fixed them — wrong (TS-023).**

F-005's spec names **only `/dashboard`.** `/`, `/profile`, and `/settings` appear nowhere in
it; the app protects four paths while the spec requires one. Pinning those three with tests
would produce **a test asserting something the spec does not require** — the very pattern §8
classifies as an "instrument defect" and fixed (TS-014), and it promotes the current
implementation to spec, which is circular.

**The measurement tool was pushing me into that circle**, because it treated all survivors
as one kind.

| What a survivor means | The right action |
|---|---|
| the spec requires it | **an evidence gap** — add the assertion |
| the spec does not require it | **a spec gap** — touching the test is TS-014 |

`spec_names()` decides this **as a fact**: does the member string appear in the spec at a path
boundary? Restricting the boundary class to **ASCII** is the crux — using `\w` makes the `에`
in `/dashboard에 접속한다` a word character, so **nothing matches**; omitting the boundary makes
the member `/` match inside `?redirect=/dashboard`, so **everything** looks spec-named.

It does not apply to line mutations — a line carries no name to look for in the spec, so
**there is no fact to decide.** An empty spec puts everything out of scope and yields no score
(there is no basis for "required").

Final F-005: **50%** (killed 3 / survived 3 / out-of-spec 3 / caught-by-types 1). The three
remaining survivors are all line mutations in `LoginForm.tsx`, whose verification belongs to
F-001–003. **F-005's collection evidence has no real gap.**

This is the **third time** in this project that collapsing a measurement into a single number
made the action wrong — a mutation score mixing in other features' files (TS-016), type-level
detection buried as "discarded" (TS-022), and two kinds of survivor merged (TS-023).
**Split the number wherever the action splits.**

### 4.3 Attaching it to another project (TS-017)

Exactly one module is tied to an ecosystem: `harness/runner.py`. Everything else
(verdict policy, tags, measurement, CLI) does not know what the runner is. Per-project
conventions are declared in **`.harness.json`**.

```bash
# 1) Inspect — infer what to check and how, printing the grounds (writes nothing)
python -m harness.cli init --harness-root /path/to/project --dry-run

# 2) If it looks right, generate the config
python -m harness.cli init --harness-root /path/to/project
```

```jsonc
// .harness.json — a declared key beats inference. Write only what is wrong.
{
  "target": "web_target",              // path to the app under test
  "runner": "jest",                    // jest | vitest | pytest
  "spec": "features.json",             // the spec file
  "id_pattern": "F-\\d{3}",            // feature ID format
  "unit_suffixes": [".test.ts", ".test.tsx"],   // tests that count as evidence
  "e2e_suffixes": [".spec.ts"],                 // do NOT count as evidence (different runner)
  "source_dirs": ["src"],
  "typecheck": ["npx", "--no-install", "tsc", "--noEmit"]
}
```

With **no config file the defaults equal the pre-externalization hardcoding** — existing
behavior does not change (confirmed at the time: **every** regression check passed both with
and without the config file present).

Output labels the provenance of every value. **`default` is a confession that the value was
chosen without grounds** — override just that line in `.harness.json`.

```
[measured] runner = vitest
           └ package.json lists vitest as a dependency
[default]  typecheck = (none)
           └ no tsconfig.json — mutation validity checking will be skipped
```

#### Adding another ecosystem

Add a `Runner` subclass to `harness/runner.py` and implement four operations.

| Operation | What it returns |
|---|---|
| `run_all()` | the whole suite (exit code, output) |
| `results()` | **individual test names and statuses** — the gate looks for tests citing the feature ID |
| `coverage(files, pattern)` | **executed statements per source file** when only those tests run |
| `typechecks()` | whether the code is statically valid (mutation validity check) |

Every operation returns `(value, diagnostic)`, and a `None` value means **measurement failed.**
A failed measurement is not a pass — the gate treats it as a rejection.

#### A project with no tests at all

The gate demands "a passing test that cites the feature ID," so it **rejects every feature.**
That is the design working as intended, but it is unusable. `inspect` enumerates everything
that blocks you:

```
→ 3 things to resolve before attaching:
   1. Cannot run the runner (vitest). Add it with `npm install -D vitest`.
   2. There are 0 test files. ... attaching now would reject every feature
   3. No spec (features.json). This is the one input a human must supply
```

### 4.4 What can be judged without intent — `inspect`

> *"Do I have to define the tests myself? Can't you inspect the project and set up
> objective evaluation metrics?"*

Half of it is possible. Where the boundary sits is what matters.

| | What it is | Who decides |
|---|---|---|
| **Spec** (`features.json`) | "what ought to be true" = **intent** | a human |
| **Invariant** | whether **two points inside the code disagree** | the machine |

**Circularity and invariants are different.** This distinction was the most expensive lesson
in this project (TS-013).

- Circular — read implementation A, write a spec from it, then check A. Always passes. Meaningless.
- Invariant — check that declaration D and implementation I **agree.** If either is wrong, it's caught.

`PROTECTED_PATHS` in `routes.ts` and the route registration in `App.tsx` are **two distinct
points.** "Is every declared path registered?" was extracted from the code yet is not circular —
deciding it requires no intent about *what ought to be protected.*

`inspect` reports the two categories separately.

**Automatically decided** (`auto=True`; exit code 1 can block CI)

| Check | Declaration ↔ Implementation |
|---|---|
| `dead-script` | npm scripts ↔ dependencies (reproduces TS-012) |
| `route-completeness` | path-list constant ↔ router registration |
| `untested-source` | source dirs ↔ imports in tests (coverage 0 guaranteed) |
| `unreferenced-export` | exports ↔ imports across the project |

**Needs intent** (`auto=False`; presented as candidates only — does not affect exit code)

| Candidate | Why the machine cannot decide |
|---|---|
| `form-rules` | there is a form. **What ought to be rejected** is written nowhere in the code |
| `error-path` | `await` with no error branch. What to show on failure is intent |

```bash
python -m harness.cli inspect --write-draft   # generates features.draft.json
```

The draft is **never written into `features.json` directly.** Doing so would make the harness
check code against a spec it derived from that same code — circular. Each entry carries
`origin` and `needs_review` so it cannot blend in with its provenance erased.

#### Stating the limits of static analysis

On the first run, 4 violations were reported and **2 were false positives** (both fixed).
This project had already reached the same conclusion from mutation scoring —
**a misleading number is worse than no number.**

- Routes generated via `.map()` were reported as "missing" → iterating the list makes omission
  **structurally impossible**, so it passes. When literal and variable registration are mixed,
  judgment is **withheld.**
- `/login` not being in `PROTECTED_PATHS` was reported as a violation → the reverse direction
  has no grounds; a path list is normally a subset. The reverse check was deleted.
- The inline `type` qualifier in `import { type ProtectedPath }` was not stripped, so a used
  type looked unreferenced → fixed.

---

### 4.5 Where the evidence came from — independence (TS-020)

```bash
python -m harness.cli independence
```

The evidence ladder had stalled after two rungs.

```
name (TS-008)  →  source executed (TS-016)  →  [empty]
```

I had assumed the empty rung was mutation. It wasn't. Mutation measures **depth within one
channel**; what TS-013 exposed was **channel independence**. F-005 was green across the suite
and passed the gate, yet did nothing in a real browser — because the test **built
`<Route path="/dashboard">` itself.** If a test supplies the structure it is verifying,
that structure goes unverified.

TS-013's fix repaired **F-005 alone** via `routes.ts`. The policy never changed.
This command is that policy.

**It counts two facts — there is no score.**

| Fact | Question |
|---|---|
| Self-supply | Does the test **import and iterate** a collection the app declares, or **write its members out**? |
| Channel count | How many of unit / E2E tag this feature? |

```
AppRoutes.test.tsx       imports PROTECTED_PATHS → .map    → reads the declaration
ProtectedRoute.test.tsx  no import + '/', '/dashboard'     → self-supplied
```

**Severity is split.** The first implementation reported both at the same grade, and they
turned out to be entirely different things.

| Severity | Condition | Meaning |
|---|---|---|
| `enumerated` | 2+ members | the collection was reproduced by hand. Lowers the grade |
| `hard-coded` | 1 member | an expected-value assertion like `toHaveBeenCalledWith('/profile')`. Recorded as weak coupling only |

The cutoff of 2 is grounded: it is **the minimum that separates "enumerating a set" from
"naming one element."** It is a count, not a score, and the original literals are printed
so a human can check.

**The grade combines the two facts without merging them** — "reads the declaration" and
"two channels cross-check" are different properties.

| Grade | Condition |
|---|---|
| `cross-checked` | 2 channels |
| `single-channel` | 1 channel, no reproduced collection |
| `self-supplied` | reproduced collection + 1 channel ← **the TS-013 shape** |

**First measurement** (6 passing features):

```
cross-checked 5 · single-channel 1 · self-supplied 0
self-supply events: 1 enumerated · 1 hard-coded

[single-channel] F-018   unit 1 / E2E 0  ← nothing cross-checks it
[cross-checked]  F-005   unit 2 / E2E 1  ← ProtectedRoute.test.tsx enumerates /, /dashboard
```

The detector found **the exact file TS-013 is about, with nothing hardcoded.**

**It is not a gate.** The exit code is always 0. Self-supply is not itself a defect — unit
tests building fixtures is normal — the problem is when it is the **only** evidence. Turning
it into a pass/fail would require deciding "how many channels are enough," and that becomes
an ungrounded constant like `EVAL_WEIGHTS`. Accumulate the numbers first.

The remaining hole, stated plainly: a test that hand-writes **only one**
`<Route path="/dashboard">` lands in `hard-coded` and does not lower the grade. Catching it
would require inspecting the literal's **syntactic position**, which becomes a
routing-specific heuristic and breaks ecosystem neutrality.

---

## 5. Paid API mode

```bash
python main.py --task "feature description" --project ./web_target   # one feature
python night_shift.py                                               # unattended continuous run
```

| Option | Default | Description |
|---|---|---|
| `--task` | (required) | the feature to implement |
| `--project` | `./web_target` | target project root |
| `--session` | auto-generated | reusing an ID inherits that session's reflection memory |
| `--max-retry` | 5 | Reflexion iteration cap |
| `--no-stream` / `--visualize` | off | disable streaming / save a graph PNG |

### 5.1 The graph

```
START ─┬─(first run)─→ initializer ─┐
       └─(afterwards)→ orchestrator ─┤
                                     ↓
                         ┌───────→ reason (Coder: ReAct Thought)
                         │           ↓ tool calls?
                         │     ┌─────┴──────┬──────────────────┐
                         │     ↓            ↓                  ↓
                         │   act        human_check     no_progress_guard
                         │ (ToolNode)  (IRREVERSIBLE)    (no tool calls)
                         │     ↓                              ↓
                         └─────┤                          reflect ←───┐
                               ↓                              ↑       │
                           evaluate (Evaluator: grades evidence)┘      │
                               ↓                                      │
                         PASS? ─┬─ yes → done (handoff + commit)       │
                                └─ no  → reflect (Reflexion) ─────────┘
                                           ↓ max_retry exceeded
                                        escalate
```

| Agent | Role |
|---|---|
| P-01 Orchestrator | pick the next task, delegate |
| P-02 Initializer | one-time environment setup |
| P-03 Coder | the actual implementation via a ReAct loop |
| P-04 Evaluator | grades **from the tool-execution record only** (function 40 / quality 30 / performance 20 / security 10; pass at 75) |
| P-05 Reflector | 5-Why reflection → episodic memory |

**Three tool permission tiers** (`harness/tools.py`, 15 tools)

| Tier | Tools | Policy |
|---|---|---|
| `READ_ONLY` | `read_file`, `list_directory`, `read_features`, `read_progress`, `list_troubles`, `read_trouble` | no approval |
| `STATEFUL` | `write_file`, `run_tests`, `bash_command`, `git_commit`, `update_features`, `write_progress`, `log_trouble` | audit log |
| `IRREVERSIBLE` | `deploy_prod`, `delete_resource` | **the router forces a branch to `human_check`** |

### 5.2 Exit codes — separating who is at fault

| Code | Meaning | What `night_shift` does |
|---|---|---|
| 0 | `done` | move to the next feature |
| 1 | `escalated` / `cancelled` | consume an attempt; stuck after 3 |
| 2 | anything else (including silent abort) | consume an attempt |
| **3** | **LLM provider unavailable (infrastructure)** | **consume no attempt + abort the entire run immediately** |

Code 3 means quota exhaustion, auth failure, or exhausted backoff. `features.json` is left
intact, and re-running after fixing the cause resumes where it stopped. The terminal status is
**always** written by `night_shift` in a `finally` block as
`[END] exit= outcome= elapsed_sec=` (TS-009).

---

## 6. Measuring the harness itself

```bash
python -m harness.cli report
```

**Discrimination principle** — a criterion that passes every input is not a criterion.
Every feature is judged at each evidence level and the pass rate is counted. No LLM call is
involved, so it reproduces regardless of API quota.

Per-level pass counts and the discrimination figure live in
**[docs/status.md](docs/status.md)** (written by `cli status`). They are not inlined here —
the same value was once published four different ways (TS-024).

**What discrimination means**: most of what the `suite` criterion let through was an
ungrounded pass.
This number is not proof that the gate is *correct*; it is a **falsifiable measurement that the
gate does something different from having it switched off.** *(Author-measured; independent
verification needed.)*

### 6.1 What the gate actually caught (TS-015)

In tokenless mode the thing worth measuring is **not cost but the effect of the verdicts.**
The records the CLI leaves on every verdict are aggregated into four numbers.

| Metric | Meaning |
|---|---|
| Verdict distribution (pass/reject/revoke) | how often the gate rejects |
| Rejection-reason distribution | **what the session habitually omits** |
| Rejections per feature | how many times one feature was blocked before it was proven |
| **Revocations (`unmark`)** | **how often the gate was wrong** — passes that were later reversed |

The last one is the point. The only data point so far is an embarrassing one: on F-005 the gate
**passed it**, and what actually caught the bug was E2E (TS-013). That event stays in the numbers.

Grounds and methodology: [docs/comparison-revfactory.md](docs/comparison-revfactory.md)

---

## 7. Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `GOOGLE_API_KEY` | (none) | required for paid mode |
| `HARNESS_LLM_MODEL` | `gemini-2.5-pro` | switch to `gemini-2.5-flash` to continue past a limit |
| `HARNESS_LLM_MAX_ATTEMPTS` | 4 | retries for transient errors (quota exhaustion is never retried) |
| `HARNESS_LLM_BACKOFF_BASE` / `_MAX` | 5 / 60 | backoff seconds |
| `HARNESS_MAX_RETRY` | 5 | Reflexion iteration cap |
| `HARNESS_EVAL_THRESHOLD` | 75 | Evaluator pass line |
| `HARNESS_REQUIRE_TEST_EVIDENCE` | `true` | evidence gate (operator-only override) |
| `HARNESS_REQUIRE_MUTATION_EVIDENCE` | `false` | mutation gate — requires ≥1 killed mutant (~27s per feature, TS-021) |
| `HARNESS_EVIDENCE_LEVEL` | `feature` | `suite` / `feature` / `step` |
| `HARNESS_PERSISTENT` / `DATABASE_URL` | `false` / (none) | checkpointer persistence (see note) |
| `HARNESS_MEMORY_DIR` | `./.harness_memory` | episodic memory path |

> **Persistence note**: without `langgraph-checkpoint-postgres` installed,
> `HARNESS_PERSISTENT=true` falls back to `InMemorySaver` with a warning (no cross-process
> resume). To enable: `pip install langgraph-checkpoint-postgres psycopg[binary]` (TS-007)

---

## 8. Policy for defects in the test subject

`web_target` is the subject, not the deliverable. Fixing every defect as it is found turns
harness work into app work. The criterion is **"does this failure teach the harness anything?"**

| Case | Verdict | Action |
|---|---|---|
| Test label disagrees with the spec | instrument defect | fixed |
| Test asserts something not in the spec | instrument defect | fixed |
| Brittle selector (demanding `data-testid`) | instrument defect | fixed with role-based queries — **no hooks added to the app** |
| Test contradicting another feature's requirement | instrument defect | fixed |
| **4 defects in the app's auth design** | teaches the harness nothing | **not fixed** — `test.fixme` + documented reason |

The last row is the point. `AuthContext` trusts an `isAdmin` decoded on the client,
`AuthContext.login()` is dead code, and login triggers a full page reload. Fixing these means
redesigning the entire auth flow, and there is no harness lesson in it. **Weakening the tests to
match the app would be the worst choice**, so the signal was preserved instead (TS-014).

---

## 9. State files

| Path | Tracked | Contents |
|---|---|---|
| `docs/status.md` | Yes | **generated** — live measurements. `cli status` writes it; CI blocks drift with `--check` (TS-024) |
| `.harness.json` | Yes | runner/target/convention declaration. Absent ⇒ defaults equal pre-externalization hardcoding (TS-017) |
| `web_target/features.json` | Yes | 75 features + `passes` + `verification` evidence — **the source of truth** |
| `features.draft.json` | No | output of `inspect --write-draft`. **Not a spec** — a human must move it over |
| `web_target/src/routes.ts` | Yes | single source of truth for the protected-path list (shared by app and tests, TS-013) |
| `troubleshooting/` | Yes | failure-mode records + `evidence/` primary sources (count in `docs/status.md`) |
| `.harness_memory/<session>/` | Yes | Reflexion records. Injected when re-run with the same session ID |
| `.claude/skills/harness/` | Yes | the tokenless-mode procedure |
| `harness_runtime.log` | No | night-shift output. Input data for `cli report` |

---

## 10. Current state

**Measurements live in [docs/status.md](docs/status.md)** — written by `cli status`, and CI
**fails if the document and the measurement disagree** via `cli status --check` (TS-024).

```bash
python -m harness.cli status          # regenerate
python -m harness.cli status --check  # exit 1 on drift
```

What can be stated as a **fact** rather than a number:

- Every passing feature carries a recorded `verification` block — the gate enforces that
- The paid path has a smoke test that drives the graph end to end with a stubbed LLM (TS-018)
- Measured on another project: `main_portfolio` (Vite, 0 tests) reported its 3 blockers accurately

| Feature | Evidence tests | Step coverage |
|---|---|---|
| F-001 email/password login | 3 | 0/6 |
| F-002 invalid-credential error | 3 | 0/5 |
| F-003 email validation | 5 | 0/5 |
| F-004 logout | 4 | 4/5 |
| F-005 unauthenticated redirect | 24 | **3/3** |
| F-018 weekly completion chart | 2 | **2/2** |

At `step` level only F-005 and F-018 pass.

### Regression verification

```bash
# Each script prints its own pass count and exits 1 on failure.
# Counts are not listed here — they go silently stale when a script changes (TS-024).
python verification/repro_ts005.py   # LLM error classification, backoff, exit codes
python verification/repro_ts006.py   # evidence gate policy
python verification/repro_ts008.py   # spec-to-test linkage verdicts
python verification/repro_ts009.py   # measurement layer + terminal status recording
python verification/repro_ts010.py   # tokenless mode dependency isolation
python verification/repro_ts015.py   # run records + gate verdict aggregation
python verification/repro_ts016.py   # coverage gate + mutation measurement
python verification/repro_ts017.py   # config externalization, runner abstraction, inspect
python verification/repro_ts018.py   # paid-path smoke (LangGraph, zero tokens)
python verification/repro_ts019.py   # dead-config / orphan-code recurrence guard
python verification/repro_ts020.py   # evidence independence (self-supply, channels)
python verification/repro_ts021.py   # mutation operators + mutation gate
python verification/repro_ts022.py   # detection reach (sampling, collection operator) 68/68
python verification/repro_ts023.py   # what a surviving mutant means (spec-aware)
python verification/repro_ts024.py   # blocks drift in published numbers

cd web_target
npm run lint       # exit 0
npm run build      # exit 0 — produces dist/
npm test           # exits 1 on the coverage threshold even when every test passes
npm run test:e2e   # exit 0 (some are deferred with test.fixme — §8)
npx jest . --no-coverage   # same criterion the gate uses
```

`npm test` exits 1 even when every test passes, because of the coverage threshold.
**Distinguish test failure from coverage shortfall.**
E2E (`*.spec.ts`) is **not counted by the gate** — the gate runs jest only.

### Known limitations

- The Gemini project's monthly spend cap is exhausted → paid mode cannot run. Lift it, or re-run with `flash`.
- **The harness-vs-no-harness A/B was never run.** §6 is an A/B of *gate criteria*; the effect of
  the harness as a whole is unmeasured. The design stands, the number does not exist.
- Gate-verdict aggregation (§6.1) has only just begun accumulating — the sample is small.
- The paid path is **pinned by a smoke test** (TS-018), but the last end-to-end run against a real
  LLM was 2026-04-14. The stub guarantees wiring, routing, and exit codes; it does not guarantee
  prompt quality or real model behavior.
  Remaining gaps as measured at TS-018: `tools.py` 15%, `memory.py` 18%
  (re-measure with `python -m coverage`; these are a record of that moment).
- The Evaluator's LLM grading, `EVAL_WEIGHTS`, and the 75-point threshold are **constants without
  grounds.** The flags in `features.json`, however, do not depend on that score — they are decoupled.
- Whether a tagged test verifies **properly** is something the gate cannot fully see. Coverage
  requirements blocked vacuous tests (TS-016), but a test that executes code while asserting
  nothing shows up only in mutation measurement, and that is not a gate (too slow).
- Measured coverage falls short of the 80% threshold.
- **`cli deadcode` is static analysis.** It cannot see `eval` or `importlib` dynamic
  references. This repo was confirmed to have none, which is why CI uses it as a block —
  in other projects, use it as a report only.
- **Reflexion's prompt quality is unverified.** TS-018 only pinned down "the error signal reaches
  the prompt"; whether the reflection is *useful* requires a run against a real model
  (see the F-004 evidence).
- **`inspect` is static analysis.** It cannot see re-exports, dynamic imports, or reflection.
  Three false positives were found and fixed by measurement (TS-017), but more of the same kind
  may exist — review automatic verdicts by eye before using them to block.
- **pytest coverage requires `pytest-cov`.** Without it, measurement fails → the gate rejects
  (by design). The diagnostic message tells you how to install it.
- The vitest and pytest adapters are **verified by unit checks only** — they have not been driven
  end to end in a real vitest/pytest project. Only the jest path has real-environment
  verification (51/51).

---

## 10.1 CI

On every push, GitHub Actions **actually runs every declared command** — a mechanical remedy for
the defect class this project hit four times: "a mismatch between the declaration and reality
persists because nobody ran it." Tokenless mode means **it all runs with no API key** (zero cost).

| Job | Contents |
|---|---|
| `harness` | `verification/repro_ts005/…/023` + `cli deadcode` + `cli status --check` + `cli tags` + `cli independence` + `cli inspect` + `cli audit` + `cli report` |
| `target app` | `tsc --noEmit` · `npm run lint` · `npm run build` · `npx jest . --no-coverage` |
| `E2E` | `npx playwright install chromium webkit` + `npm run test:e2e` (uploads the report on failure) |

---

## 11. Failure mode catalogue

| ID | Title |
|---|---|
| TS-001 | `night_shift.py` could not find `features.json` and quietly printed "complete" |
| TS-002 | Emoji output aborted with `UnicodeEncodeError` on a Windows cp949 console |
| TS-003 | subprocess crashed in `_readerthread` decoding cp949 output as UTF-8 |
| TS-004 | Replying with text and no tools ended the graph quietly, disguising failure as exit 0 |
| TS-005 | An LLM quota overflow (429) blew up as a traceback and marked healthy features as stuck |
| TS-006 | The agent graded itself without test evidence — `run_tests` had never once worked on Windows |
| TS-007 | Checkpointer persistence was dead config — the flag was never passed, so always `InMemorySaver` |
| TS-008 | "Green suite" was mistaken for "this feature is verified" — the gate never linked feature to test |
| TS-009 | 9 of 15 runs left no terminal status, making 60% of post-hoc measurement a blind spot |
| TS-010 | The harness's value already spent no tokens — the paid API was removed from the reasoning engine |
| TS-011 | The route guard ignored `isLoading`, logging users out on every refresh, plus a `?redirect=` open redirect |
| TS-012 | All 3 commands advertised by `package.json` (lint/build/test:e2e) were non-functional |
| TS-013 | Unit tests verified routes they had supplied themselves, so F-005 did nothing in a real browser |
| TS-014 | A tag pointing at the wrong feature is invisible to the gate — and how far to fix subject defects |
| TS-015 | Half the measurement layer was orphaned by the move to tokenless mode — nobody noticed the recorder had gone |
| TS-016 | A test that executes nothing counted as perfect evidence — coverage gate and mutation measurement |
| TS-017 | The harness was bolted to one repo — config externalization, runner abstraction, project inspection |
| TS-018 | The paid path went unverified for six months — a smoke test found two real bugs immediately |
| TS-019 | Three settings the docs advertised did nothing — dead config's second recurrence, plus 21 orphans |
| TS-020 | The empty rung on the evidence ladder was independence, not depth — TS-013 generalized into policy |
| TS-021 | The mutation operators tested the compiler, not the tests — 3 of 190 match sites were real comparisons |
| TS-022 | Two holes detection never reached — sampling was pinned to the top of each file, operators could not touch arrays |
| TS-023 | I read a surviving mutant as "the test is weak" and almost fixed it — the spec never required it |
| TS-024 | The same measurement was published four different ways — a number in prose goes silently false when the measuring code changes |

Full list: [troubleshooting/INDEX.md](troubleshooting/INDEX.md)

**The recurring pattern**: "a mismatch between declaration and reality persists because it is
never executed" — it appeared four times (TS-001's root `features.json`, `init.sh`'s
`PROJECT_ROOT`, TS-006's `run_tests`, and TS-012's three commands). All of them follow from
moving the project into a subdirectory without auditing the config files left behind at the root.

---

## 12. References

- External project comparison and the grounds for the criteria: [docs/comparison-revfactory.md](docs/comparison-revfactory.md)
- Primary evidence of Reflexion fabricating a root cause with no error signal:
  [troubleshooting/evidence/F-004-reflexion-confabulation/](troubleshooting/evidence/F-004-reflexion-confabulation/)
