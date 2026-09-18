# Fork deltas from upstream

Fork: `prismatic7/anti-hallucination-protocol` (branch `customizations`)
Upstream: `antydizajn/anti-hallucination-protocol` (v5.4.2)

This documents why this fork exists and what it changes. Upstream v5.4.2 is
substantively good and its own regression suite passes unmodified. The fork
carries one correctness fix plus local deployment wiring; it is not a rewrite.

## Why this fork exists

Upstream README prescribes a **mandatory startup integration**: the skill must be
explicitly loaded at the start of every Hermes session, and it must be loaded
"alongside other baseline session controls". Upstream assumes a `/start` boot
skill exists to edit. On the target hosts there is no `/start` skill and no
config-level skill preload, so that instruction cannot be followed as written.

The fork therefore adds the boot-hook integration layer upstream does not ship.
Everything else is upstream plus the single fix below.

## Fix 1: a cannot-run checker is ERROR, not FAIL

**File:** `scripts/check_v5_integrity.py`, `scripts/liveness_check.sh`
**Severity:** correctness of the project's own central invariant

`check_v5_integrity.py` imports PyYAML, which is a documented requirement. When
PyYAML was missing it did not report that it could not run. It fell through to
`validate()`, where `yaml is None` made `parse_frontmatter` return an empty
mapping, producing:

```text
V5 INTEGRITY: FAIL
- PyYAML is required for Hermes-compatible frontmatter validation
- SKILL.md frontmatter missing required key: name
- SKILL.md frontmatter missing required key: description
- ... (every required key)
exit 1
```

Those "missing required key" findings are vacuous: the keys could not be read at
all. The exit code and the verdict word said the *skill's contract was violated*
when the truth was that the *checker could not evaluate it*. That is exactly the
`ERROR -> NOT_FOUND` collapse the protocol forbids in its own hot path rule 5.

`liveness_check.sh` inherited the collapse at L2, reporting:

```text
[FAIL] v5.4.2 repository-local integrity checker failed
```

### Reproduced, not theorised

On a host whose `PATH` `python3` is a linuxbrew interpreter without PyYAML:

```text
python3 scripts/check_v5_integrity.py --root .        -> V5 INTEGRITY: PASS   (interpreter with PyYAML)
AHP_SKILL_DIR="$(pwd)" bash scripts/liveness_check.sh -> FAIL (portable L1/L2)
python3 -c "import yaml"                              -> ModuleNotFoundError
```

The documented invocation failed while a direct run of the same checker passed.
The difference is only which interpreter each one found.

Why upstream CI and the suite did not catch this: CI installs `pytest pyyaml`
before running, and `pytest tests/` executes the liveness tests in a process
whose `PATH` already resolves to the PyYAML-bearing interpreter. Any runner that
injects PyYAML masks the defect.

### Change

`check_v5_integrity.py` now returns exit `2` with an explicit `ERROR` on stderr
when PyYAML is unavailable, and emits no verdict on the contract. The three
outcomes mirror `verify_claim.py`:

```text
exit 0  PASS   - contract holds within the checker's stated scope
exit 1  FAIL   - checker ran correctly; the contract was violated
exit 2  ERROR  - checker could not run correctly; no verdict returned
```

`liveness_check.sh` probes for any interpreter on the host that can import
PyYAML (`python3`, then `python3.14` downward, then `/usr/bin/python3`), runs the
checker with the one it found, reports that interpreter, and distinguishes:

```text
[OK]   ... checker passed (interpreter: python3)
[FAIL] ... checker FAILED: the contract was violated
[FAIL] ... structural checker could not complete (ERROR, exit N): no verdict on the contract
```

The `FAIL` prefix is retained for the cannot-run case because it remains a
required-check failure that exits nonzero; the wording now names the condition
correctly instead of asserting a contract violation.

### Tests

`tests/test_yaml_error_distinction.py` adds five regression tests. All five fail
against unpatched upstream and pass against this fork, which was verified by
copying the tests onto a clean upstream checkout.

## Version pinning

`EXPECTED_VERSION` stays `5.4.2`. Upstream's contract deliberately pins the exact
release version and several tests assert that other v5 releases are rejected.
Bumping it would break the release-integrity contract and upstream tests; the
patch is reported through this document and the commit history instead.

## Local deployment (not upstream-shaped)

Both target hosts install the full repository tree at:

```text
~/.hermes/skills/software-development/anti-hallucination-protocol/
```

The full tree is required, not just `SKILL.md`: `check_v5_integrity.py` validates
25 required repository paths including `README.md`, `references/`, `scripts/`
and `tests/`. Installing `SKILL.md` alone would fail the project's own integrity
contract.

Host note: on the Linux host, `python3` resolves to linuxbrew 3.14.7 without
PyYAML, while `/usr/bin/python3` (3.13.5) has it. This is precisely the condition
that produced the collapse above.

## Boot hook: `skills.auto_load`

Upstream's README requires the skill to be explicitly loaded before consequential
work in every session, and assumes a `/start` boot skill to edit. Neither target
host has a `/start` skill (`~/.hermes/skills/get-oriented/` is the closest thing
and is not a boot loader), and `hooks.on_session_start` runs external commands
rather than loading skills.

The mechanism that actually exists in Hermes is `skills.auto_load`:

```yaml
skills:
  auto_load:
    - anti-hallucination-protocol
```

`hermes_cli/config_defaults.py` describes it as "Skill names pinned as fully
loaded in every new session (CLI, TUI, gateway, cron, API)", resolved once per
agent lifecycle and injected as full skill blocks into the system prompt. Its
default is `[]`, and the injected block carries the standard line: "Treat its
instructions as active guidance for the duration of this session unless the user
overrides them."

**Cost, measured.** `SKILL.md` is 14,096 bytes / 225 lines, roughly 3,500 tokens,
paid in every session on every surface where the skill is pinned. That is the
real trade-off, not a formality: it buys always-resident discipline at the price
of permanent context. Three options, in ascending cost:

1. **Discoverable only** (current state). Installed and enabled; loads on demand
   via skill search. Zero standing cost. Upstream would call this "installed but
   not active".
2. **Pointer digest.** A short always-resident note that instructs the agent to
   load the full skill when a claim turns consequential. Cheap, but introduces a
   second artifact that can drift from `SKILL.md`.
3. **Full pin.** `auto_load: [anti-hallucination-protocol]`. Matches upstream's
   stated requirement exactly; costs the full prompt in every session including
   purely creative or T0/T1 work.

Option 3 is the faithful reading of upstream's install contract. It has not been
applied to the hosts in this fork's commit history because it is a global,
every-session configuration change rather than a skill installation, and it
belongs to the operator to accept the standing context cost.

Whichever is chosen, verify it took effect rather than assuming: a healthy boot
must visibly show the skill loaded. "Installed" and "active" are not the same
claim.

## Syncing from upstream

```bash
git fetch upstream
git merge upstream/main
```

The fix is confined to two scripts plus one new test file, so upstream rebases
should stay tractable. If upstream fixes PyYAML handling itself, drop Fix 1 and
keep only the version-pin rationale if it still holds.
