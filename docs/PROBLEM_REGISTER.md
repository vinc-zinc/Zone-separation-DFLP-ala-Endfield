# Problem register — FLP GA/SA notebooks

Open issues only. Things already fixed are recorded here with what was done and
what it measured; older fixes are in `REVIEW_GA_SA_fixed.md`.

Each entry: what's wrong, the evidence, why it matters, and what was done.

Ordered by how much sits downstream of it, not by effort.

Backups of the four notebooks as they were before this session:
`_backup_20260812/`.

---

## READINESS — where the two notebook families stand

Both families **run**: 0 execution errors, 0 crater violations, every phase
emits its output.

| | `_fixed` | `_pool` |
|---|---|---|
| Runs end to end | yes | yes |
| Crater respected | yes (asserted) | yes (asserted) |
| Scenario sets (10 craters) | yes | **yes — ported this session** |
| Regret is meaningful | yes | yes |
| Recovery search has traction | **yes — R4 fixed** | **yes — R4 fixed** |
| GA/SA comparable | yes — same neighbourhood, same repair | yes |
| Damage separable from recovery | **yes — R1 fixed** | yes |
| Recovery optimises what is reported | **no — R5** | **no — R5** |
| Phase 1 actually searches | yes — S2/S3 fixed | yes — S2/S3 fixed |
| Simulation contradicting the analytic rate is caught | yes — S1 fixed | yes — S1 fixed |
| Build costs real | n/a | **no — no source data exists** |
| Grid matches the source spec | **no — 70×70 vs 50×50** | **no** |

**What changed this session.** Both families were reporting a recovery
comparison that could not show a difference (R4) and a regret that mixed the
bomb with the recovery (R1). Both are fixed. The `_pool` fork was additionally
found to have been branched from a pre-G1, pre-R0 `_fixed` and had silently lost
four fixes; those are ported.

**What the fixes then exposed.** With a baseline to compare against, the
recovery can now be seen going *backwards* on the reported metric in some
scenarios — because it optimises a different function from the one Phase 4
reports. That is **R5**, it is a methodology decision rather than a defect, and
it is the thing to settle before the next full run.

**Still not safe to quote:** anything computed on the quick profile; anything
that depends on the grid being 50×50 (N1); any GA-vs-SA recovery claim until R5
is settled; and **anything at all from a run made before S1–S3 were fixed** —
that search froze at generation 4 and discarded its own best layout, and its
Phase 5 reported agreement between an analytic 7.0000 and a simulated 0.000.

---

## B1 — Phase 4 budget: unequal between variants, and larger than it needed to be — **FIXED**

The GA's full run was slow because of the budget, not the machinery:

```
    before                                             evaluations
    GA  620 evals x 10 scenarios x 10 layouts  =  62,000
    SA  500 evals x 10 scenarios x 10 layouts  =  50,000

    after
    both 300 evals x 5 scenarios x 5 layouts   =   7,500   (8.3x less for the GA)
```

**The unequal budget was the real defect.** The GA had 24% more evaluations per
recovery than the SA, so any advantage it showed was partly just the extra
budget. `ZPF_ITERATIONS` is now 300 in both notebooks and must stay matched.

**`ZPF_EARLY_STOP = 100`** (new) abandons a recovery after 100 evaluations
without improving its record. This is what makes the depth cut defensible rather
than arbitrary: instead of asserting 300 is enough, each run records
`recovery_log["stopped_early"]` and `["evals_to_best"]`, so the budget actually
consumed can be quoted. If recoveries routinely stop early, 300 is generous; if
they routinely run to the wall, raise it and say so. Set to 0 to disable.

Counted in **evaluations**, not generations, so the threshold means the same
thing in the SA walk and in the NSGA-II loop.

### Verified, and one residual asymmetry

Tested by forcing the branch — a quick run never reaches a threshold of 100, so
"the quick profile passes" is no evidence at all here. Copies of both `_fixed`
notebooks were run with `ZPF_EARLY_STOP` pushed through `_QUICK_ZPF`:

```
SA,  ZPF_EARLY_STOP=4,  budget 20  -> stops at 5 evaluations, every scenario,
                                      logs "(stopped early)"
GA,  ZPF_EARLY_STOP=6,  budget 60  -> "Stopped at gen 2/9: 6 evaluations
                                      without improving the record"
```

Both work. But **the two variants stop at different granularities**:

| | can stop | threshold 100 first reachable at |
|---|---|---|
| SA | after any evaluation | exactly **100** stagnant evaluations |
| GA | only at a generation boundary | ~**120** (3 stagnant generations × 40) |

The SA tests per evaluation; the GA accrues stagnation in whole-generation
chunks of `2 × (pop_size // 2)` evaluations and can only test at the top of a
generation. At the full profile (300 evals, pop 20 → 14 generations of ~40) that
is a **~20% larger effective stall allowance for the GA**, i.e. ~13% of the
total budget.

That matters because equalising the budget was this item's whole purpose: the GA
previously had 24% more evaluations per recovery, so any GA advantage was partly
just budget. The stopping rule reintroduces a smaller version of the same bias,
in the same direction. Bounded and arguably fine — but it should be a stated
choice, not an accident.

Two ways to close it: test stagnation inside the offspring loop rather than at
the generation boundary, or set the GA's threshold to
`ZPF_EARLY_STOP − evals_per_generation` so both first stop at the same
evaluation count. Not changed here — it is a comparison-design decision.

*(Also why the GA showed no early stop on the quick profile: `ngen = 2` there,
the check runs at the top of each generation, and stagnation is credited only
after a generation completes — so it can never fire. Not a fault, just a budget
too small to exercise it.)*

Scenarios were cut 10 → 5 and `PHASE4_TOP_N` 10 → 5 on request. Note the tension
with R0's advice — the regret distribution is the evidence, so if runtime later
allows, restore scenarios before restoring depth.

### On seeds — GA 42 vs SA 60

Checked directly: the two notebooks are **identical code except the config cell,
the recovery cell, and trailing whitespace**. Phase 1 is the same NSGA-II in
both.

So the layouts differ *only because the seeds differ*. Matching the seed would
make Phase 1 produce the **same layouts** in both notebooks, turning an unpaired
comparison into a paired one — each recovery method attacking the same layout
under the same crater. That is a much stronger design: it removes layout
variance from the comparison entirely, which is otherwise the largest source of
noise between the two runs.

Against that, `CFG.MULTIPROCESSING = True` on full runs means Phase 1
reproducibility should be confirmed before relying on it.

Not changed — it invalidates the existing full results, so it is the user's
call. Worth doing before the next full pair.

---

## S1 — Phase 5's agreement check missed total production failure — **FIXED**

Reported from a full run: layouts #1 and #2 posted analytic rates of **7.0000
and 6.2000 against 0.000 simulated revenue/tick** — two of three simulated
layouts produced nothing — and Phase 5 printed

```
[OK] Static Gate 2 and the simulation agree on every simulated layout.
```

**The check only ever compared equilibrium TIMING**: the static
`chain_time <= SIM_EQ_MAX_TICKS` against the simulated `eq_tick`. Whether the
factory produced anything was never part of it, so a layout that makes nothing
at all passes as long as its critical path is short. The two failures also had
different causes — #1 starvation, #2 power collapse (`live_fraction=0%`,
brownout 250/400, pool drained) — and nothing distinguished them.

**Fixed.** `diagnose_simulation()` and `explain_simulation()` (cell 30), and
Phase 5 now runs **two independent checks**:

1. **Timing**, as before.
2. **Throughput** — the simulation must reach `CFG.SIM_AGREE_FRACTION` (0.5) of
   the analytic rate. Zero production against a positive analytic rate is now
   `[!!]`, and the summary table carries a `cause` column.

Causes are named, so two different failures are never conflated again:

| cause | how it is decided |
|---|---|
| `power` | post-grace brownout fraction ≥ `CFG.SIM_BROWNOUT_FRACTION` |
| `starvation` | machines never ran / starved at the end / low live_fraction |
| `no-supply` | the injection map is empty — the chain has no root |
| `throughput` | produces, but well under the analytical claim |

**Brownouts are measured against POST-GRACE ticks, not total ticks.** Power is
free for the first `POWER_GRACE_TICKS` by construction, so counting them
understates the failure: the reported "brownout 250/400" is 100% of the ticks
that layout was actually charged for, not 63%.

Both branches were verified by forcing them, since a healthy quick run exercises
neither:

```
SIM_MAX_TICKS=12   -> [!!] analytic 3.0000 -> sim 0.000 | STARVATION -- 8/13
                          machines never ran, 4 starved at the end, live 56%
POWER_GRACE_TICKS=0 -> [!!] analytic 3.0000 -> sim 0.000 | POWER COLLAPSE --
                          browned out 119/150 post-grace ticks (79%),
                          demand 100/tick
```

The power case also caught a second-order version of the same mistake: `dead`
and `short` were reported with `if/elif`, so a layout that merely
under-produced was hidden whenever another produced nothing. They are reported
independently now.

---

## S5 — Recovery re-routed the whole factory, not the damaged part — **FIXED in the two `_fixed` notebooks**

(`TASK_preserve_belts`. Applied to `flp_definitive_GA_ALNS_fixed.ipynb` and
`flp_definitive_SA_ALNS_fixed.ipynb` only; the `_pool` pair still re-routes
everything.)

`recover()` and `post_bomb_state()` both built a fresh `FactoryGrid` and
re-routed **every** flow, including the ~90% of the factory a 3×3 crater never
touches. The original belts were laid incrementally — BLF → ALNS → Tabu →
connect_or_remove → repair_feasibility, each fitting into the space the last one
left — so re-laying them all in a single pass is a different and worse
procedure. Re-routing an *undamaged* layout dropped its rate 8.4337 → 1.5372
(−82%), and that swamped the measurement:

```
            pre-bomb   re-route effect   mean regret
GA  #4       8.4337        -6.8965          6.9410     <- 99.4% is re-route
SA  #3       7.5110        -6.9449          6.9463     <- 99.98% is re-route
```

It is also physically wrong: a factory does not rip up its entire conveyor
network because one machine exploded.

**Fixed.** `_reuse_belts()` / `_route_with_reuse()` re-lay a belt when it still
has a path, both endpoints exist at the same coordinates **and rotation**, no
tile is in the crater, and every tile is still free; everything else routes
normally. Called from both sites so the two states are built identically.
`CFG.ZPF_PRESERVE_BELTS = False` restores the old behaviour.

Two implementation points beyond the task spec:

- **Rotation is part of the endpoint match.** The spec said "same coordinates",
  but `ZPFNeighbourhood`'s `rotate` operator (P7) can leave a machine on the
  same corner with its I/O faces on different sides. `place_belt` would not
  catch it — the tiles are still free — and the belt would attach to nothing.
- **Keyed by object identity, not `(src, dst, material)`.** `derive_flow_matrix`'s
  multi-output handling emits several flows between the same pair carrying the
  same material on different port slots; a value key collides and swaps their
  paths. With `ZPF_PRESERVE_FLOWS` the flow objects are the ones in
  `base["flows"]`, so identity is exact, and if it is ever off nothing matches
  and everything routes normally — the correct fallback.

### Verified, quick profile

```
                    re-route effect      belts preserved (reference)
GA _fixed  #1           +0.0000            18/18 (100%)
GA _fixed  #2           -0.1028            42/42 (100%)
SA _fixed  #1           +0.0000            30/30 (100%)
```

**Every reference state preserves 100% of its belts**, which is the direct check
that the mechanism works: with no crater, nothing should be invalidated.

Crater integrity 0 violations throughout (12 states GA, 6 SA), 0 errors, and
runtime fell GA 102.0s → 77.1s, SA 51.6s → 43.2s.

Belt reuse across the three states — the mechanism, not just the outcome:

```
                        reference   un-recovered   best recovery
SA _fixed  #1            30 (100%)      26             22
GA _fixed  #1            18 (100%)      15             12
GA _fixed  #2            42 (100%)      38             38
```

100% with no crater, dropping as the blast cuts belts and then again as the
recovery relocates machines (a moved or rotated machine invalidates its own
belts). GA #2 is the informative case: 38 preserved in both damaged states,
i.e. its recovery moved nothing that carried a belt.

**The one residual is correct behaviour, not a leak.** GA `_fixed` #2 keeps a
−0.1028 reference effect. Its gates read `route 1.00` both pre-bomb and in the
reference — every belt *was* preserved — and only `sust` moved, 1.00 → 0.90. The
cause is that flows which were **unrouted** in the base result are still
re-attempted, and on a grid where the preserved belts are already laid one of
them now succeeds, adding an edge to the chain graph. Refusing those retries
would make the reference exactly 0.0000 and would be wrong: post-bomb, a flow
whose route is blocked *must* be re-attempted. Worst case improved from −6.94 to
−0.10, so regret is no longer swamped.

**Not done, deliberately:** changing `regret` to measure against `ref_rate`. The
task marks it "do NOT do at the same time", and with the re-route effect at ~0
the evidence now says it is unnecessary.

**Expected side effect, stated rather than treated as a regression:** the
recovery inherits a working belt network instead of rebuilding one, so its
`gain` is smaller. That is honest. It applies equally to both variants (shared
`_finalise_recovery` and `ZPFNeighbourhood`), so the GA-vs-SA comparison stays
fair.

---

## S4 — Phase 2 selected candidates the GA had already rejected — **FIXED**

`evaluate_nsga2` never actually evaluates an individual whose BOM exceeds
`MAX_MACHINES`. It returns early with a graded penalty and, in place of a
measured `terminal_rate`, **`raw_terminal_rate * 0.1`** — a discounted sum of
(product rate × price) that was never costed, placed or routed.

For an ambitious BOM that discounted figure is still large, and Phase 2 sorts by
exactly that key (`fitness.values[1]`). So over-cap individuals outranked
properly evaluated ones and were selected. Measured on the quick profile with
`MAX_MACHINES = 40`, before the fix:

```
GA _pool   Phase 2 candidates of 148, 105 and 94 genes
GA _fixed  Phase 2 candidate  of 118 genes
```

The heavy repair budget (ALNS ×3, Tabu ×2, rotation polish) was being spent on
layouts the search had already rejected, and those layouts then flowed into
Phase 4 and were bombed. Every number derived from them — feasibility, regret,
recovery gain — describes a factory larger than the model permits.

**Fixed.** The Phase 2 selector skips any individual over the cap and walks
further down the ranked list (`CFG.PHASE2_ENFORCE_CAP`, default on). It reports
how many it skipped and their size range, and states that their fitness was a
penalty rather than a measurement.

If **nothing** is under the cap it falls back to the smallest BOMs and says so
loudly, because an empty Phase 2 breaks every phase after it — and a population
entirely over the cap means `MAX_MACHINES` or the terminal-rate band is mis-set,
not that those layouts are acceptable. This matters most on the `_pool` fork,
where `SELF_FUEL_POWER` makes BOMs 50–130% larger for the same target rate.

The de-duplication key is now computed from the `chromosome_for()` call the
filter already needs, instead of calling `genotype_key()` to re-derive the same
BOM a second time.

### The over-cap penalty also feeds S2's front saturation

Worth spelling out, because the two defects share a mechanism. The penalty
returned for an over-cap individual is

```python
return (penalty, raw_terminal_rate * 0.1, penalty)     # weights (-1, +1, -1)
```

so objectives 0 and 2 are ~1e5 (terrible) while objective 1 is the discounted
raw rate. An in-cap individual `Y` has cost in the hundreds and MHC in the
thousands, so `Y` beats an over-cap `X` on both of those automatically —
meaning **`Y` dominates `X` if and only if `Y`'s rate is at least `X`'s**. If
the discounted raw rate exceeds every properly measured rate in the population,
the over-cap individual is dominated by nothing and sits on the first front
permanently.

So over-cap individuals are not rejected by the search at all: they are made
*non-dominated*, which inflates front 1 (S2) and puts them at the top of the key
Phase 2 sorts by (S4). The penalty was intended to push the population back
under the cap and instead pinned it above.

Not changed here, because altering the penalty changes what the GA optimises and
that is the author's call. Two options if it is worth doing: return a rate of
0.0 for an over-cap individual so it is dominated by anything feasible, or clamp
the reported rate to the best in-cap rate seen so far.

### Measured effect, quick profile at MAX_MACHINES=40

```
GA _fixed     4 of 10 over cap ( 74-118 genes)  ->  3 candidates   102.0s
SA _fixed     9 of 10 over cap ( 41-127 genes)  ->  1 candidate     51.6s
GA _pool     10 of 10 over cap ( 44-148 genes)  ->  FALLBACK       301.5s
SA _pool     10 of 10 over cap ( 41-127 genes)  ->  FALLBACK       219.9s
```

All four complete with 0 errors and crater integrity intact.

SA `_fixed` runtime fell from 256.5s to 51.6s, purely from not running the heavy
repair on layouts that were never eligible.

**Neither pool notebook can produce a single in-spec layout at
`MAX_MACHINES = 40`** — both hit the fallback with the entire population over
cap. That is a real incompatibility between the cap and `SELF_FUEL_POWER`
(which inflates BOMs by 50–130%), and it was invisible before this filter
because the over-cap layouts went straight through Phase 2. It must be resolved
before any pool number is quoted:

```
[!] EVERY ranked individual exceeds MAX_MACHINES=40.
    Falling back to the 3 smallest BOM(s) (41 genes and up) so the pipeline
    can continue.
    These layouts are OUT OF SPEC: raise MAX_MACHINES, or lower
    MIN/MAX_TERMINAL_RATE so the BOMs fit the cap.
```

The pipeline completed with 0 errors and the results are labelled out-of-spec
rather than silently reported as valid — which is the point. Without the
fallback Phase 2 would have been empty and every phase after it would have
failed on an empty `refined`.

**A configuration note this exposes.** The quick profile pairs
`MAX_MACHINES = 40` with a terminal-rate band of 0.02–0.06 and
`PRODUCT_ACTIVATION_PROB = 0.4` over six products, so several products are
active per individual and the BOMs land at 41–127 machines — most of the
population is over the cap before the search starts. Either raise the quick
profile's `MAX_MACHINES`, or lower `PRODUCT_ACTIVATION_PROB` for it. Left alone
because it changes what the smoke test covers.

---

## S2 — NSGA-II stopped searching at generation 4 — **FIXED**

Reported: best rate frozen from generation 4 to generation 50, average rate
collapsing and then freezing, **all 200 individuals on the first Pareto front**.
46 of 50 generations bought nothing, so the layouts Phase 4 bombed were
effectively the generation-4 population.

Two compounding causes.

**1. There was no mating selection at all.** `algorithms.varAnd(pop, ...)` was
handed the population directly, so every individual reproduced regardless of
quality and the only selection pressure anywhere in the loop was the
environmental step. Textbook NSGA-II picks parents by binary tournament on
(rank, crowding) first. Now `tools.selTournamentDCD`, with the initial
population ranked once up front so the crowding distances it reads exist.

**2. The first front saturated.** `derive_rate_balanced_bom` is a step function
of the genome (`ceil()` rounding), so large regions of genotype space map to the
**same objective vector**; the reported run held 200 individuals carrying about
9 distinct `(cost, rate, MHC)` triples. Individuals with identical objectives
cannot dominate one another, so they all land on front 1 — and once the whole
population is rank 1, `selNSGA2` degenerates into pure crowding distance, which
rewards *spread* rather than quality. It keeps the extremes, including the
cheap-and-useless corner. That is why the best rate froze while the average
collapsed.

`CFG.GA_MAX_CLONES` (2) caps how many individuals sharing one objective vector
survive a generation; the freed slots take a bounded `CFG.GA_FRESH_BLOOD` (10%)
of newly sampled individuals, and the remainder refills from the ranked
overflow. Deduplicating outright and refilling at random was rejected: with 9
distinct vectors among 200 that is a restart every generation, not a fix.

Measured, Phase 1 only, POP=24 NGEN=10, same seed:

```
gen   OLD: front1/distinct/best-rate     NEW: front1/distinct/best-rate
  4        12/24    6   3.9768                4/24   15   2.8571
  6        24/24    2   3.2982                6/24   21   2.8571
  7        24/24    1   2.8571                6/24   19   2.8571
 10        13/24   10   2.8571                8/24   14   3.2982
```

The old configuration collapses to **one distinct design across the entire
population**. The new one never saturates and stays at 14–21 distinct.

The per-generation line now prints `front1=X/POP distinct=Y fresh=+Z`, and the
run ends with `N/NGEN generation(s) improved the best rate` plus an explicit
warning if the front still fills the population — so this cannot fail silently
again.

---

## S3 — The best-rate individual was being discarded — **FIXED**

Found while A/B-testing S2, and worse than the reported symptom. The old
configuration does not merely freeze: **it regresses**. Best rate 3.9768 at
generation 4, then 3.2982, then 2.8571 for the rest of the run. The best layout
the search had found was thrown away.

**NSGA-II is Pareto-elitist, and that guarantees nothing about any single
objective.** Once the first front is larger than the population, survival is
decided by crowding distance alone, and a high-rate individual sitting in a
crowded region of objective space loses to a worse one at the edge of the front.
Phase 2 and Phase 4 both select by rate, so this is the pipeline discarding
exactly the layouts it exists to study.

`CFG.GA_RATE_ELITISM` retains the best-by-rate individual ever seen and
re-injects it over the worst-by-rate if it drops out, re-ranking afterwards so
the next mating round reads consistent crowding distances. The reported best
rate is then monotone by construction.

Verified in isolation — old selection, so the front still saturates, but with
elitism on:

```
gen    without elitism      with elitism
  4        3.9768              3.9768
  6        3.2982              3.9768
  7-10     2.8571  (lost)      3.9768  (held)
  [elitism] the best-rate individual was dropped by crowding-distance
            selection and restored 1 time(s).
```

Identical up to generation 5, then the champion is restored once and the best
rate holds instead of collapsing.

---

## R4 — The recovery metaheuristic had almost nothing to search — **FIXED**

**This was the one blocking RQ2.** Not a crash: the reason a GA-vs-SA recovery
comparison could not show a difference.

Both variants searched a **permutation of the movable machines** and handed it
to `recover()`. But step 1 of that repair puts every *undamaged* machine
straight back at its original coordinates, and those coordinates came from a
layout that was already collision-free — so they always succeed, in any order.
The permutation only mattered for machines that were actually destroyed, and the
crater is 3×3, so that is typically **one machine**. Permuting a 10-element list
changes the result only if two elements contend for the same cell, which they
almost never do.

Measured before the fix (quick profile, `ZPF_ITERATIONS = 20`, per scenario):

```
L0 S0 SA: 20 evals, best@1,   2 DISTINCT costs of 20
L0 S1 SA: 20 evals, best@1,   4 DISTINCT costs of 20
L0 S2 SA: 20 evals, best@1,   1 DISTINCT cost  of 20
L1 S0 SA: 20 evals, best@3,   2 DISTINCT costs of 20
L1 S1 SA: 20 evals, best@1,   1 DISTINCT cost  of 20
L1 S2 SA: 20 evals, best@10,  3 DISTINCT costs of 20
```

80–95% of every iteration budget re-evaluated a layout already seen, and the
best was usually found on evaluation 1 — i.e. by the deterministic repair
heuristic, before the metaheuristic did anything. Both variants were wrappers
around the same repair, so a null result was the expected outcome and would not
have been evidence about the methods.

**Implemented: option (a), the position-based neighbourhood.** `ZPFNeighbourhood`
(cell 33) is a destroy-and-reinsert operator set over **coordinates**, shared
identically by the NSGA-II and the SA recovery so the comparison is about the
search strategy and nothing else. A solution is now `(order, anchors,
rotations)`:

- `order` — the sequence machines claim space in. Still meaningful: it decides
  who wins a contested cell.
- `anchors` — `instance_id -> (x, y)`, or absent meaning "put it back where it
  was". `_zpf_place` tries the anchor cell first, then spirals outward from it
  instead of from home.
- `rotations` — which face carries the I/O ports (see P7).

Operators: `random` (destroy *k*, reinsert at uniformly-sampled cells inside
r2), `greedy` (destroy *k*, reinsert at whichever of `ZPF_GREEDY_SAMPLES`
sampled cells minimises Manhattan distance to the machine's flow partners — the
greedy insertion ALNS is normally run with), `shift`, `restore` (the undo move,
which the avoidable-relocation penalty makes valuable), `swap`, `rotate`,
`order` (the only move the old neighbourhood had).

Individual 0 / the SA's starting incumbent is still the deterministic repair, so
the search can never return something worse than the heuristic it replaced.

Measured after the fix, same profile and budget:

```
                    distinct costs / evaluations     evals-to-best
GA  _fixed          13.3 and 11.0 of 18              14, 16 of 18
SA  _fixed          12.7 and 12.3 of 20              15, 3 of 20
GA  _pool           13.0 and 13.3 of 18
SA  _pool           10.8 of 20
```

1–4 distinct costs became 10–16. The budget now buys something: on GA `_fixed`
layout #1 scenario 1 the permutation search reached 3.6884 where the position
search reaches 4.0000 on the same crater.

`CFG.ZPF_POSITION_SEARCH = False` restricts the operator set to `order` alone
and reproduces the old behaviour exactly — which is how option (d), "recovery is
dominated by the repair heuristic and the metaheuristic contributes little", can
now be *measured* rather than asserted.

*(Numbered R4 to avoid the pre-existing R2 on the logistics network below.)*

---

## R1 — No baseline separating "bomb damage" from "recovery quality" — **FIXED**

`regret = pre_bomb_rate − post_recovery_rate` conflates how bad the disruption
was with how well the algorithm recovered. Two methods can post identical regret
while contributing very differently, and a layout that was barely hit reports
low regret regardless of the recovery.

**Implemented.** `post_bomb_state(base, disruption)` (cell 33) builds the
un-recovered damaged layout: crater blocked, its machines gone, everything else
exactly where it was, belts re-routed, and **the pre-bomb supply plan carried
over** (this is also the P8 fix). It deliberately does *not* run
`_finalise_recovery` — the reconnection polish and the depot spawning are
recovery, and this is the state before any of it.

Phase 4 now reports three states per scenario and three metrics:

```
      # 1 crater(13,39)  destroyed=1 movable=  5  rate  3.5000 ->  0.4405 ->  3.5000
                                        regret= 0.0000  gain=+3.0595  frac=100.0%
```

- `regret` keeps its original definition against the reported pre-bomb rate,
  because that is what the thesis quotes.
- `gain = post_recovery − post_bomb` — what the recovery actually contributed.
- `frac = gain / (ref − post_bomb)` — normalised, comparable across layouts of
  different sizes and damage levels. This is the quantity a claim like "SA
  recovered 62% of lost throughput where GA recovered 71%" needs.

Phase 6 draws its middle panel from the same object Phase 4 scored, so the
figure and the number can no longer disagree.

### Three accounting defects found while doing it

**The routing gate rewarded destruction.** Routing was scored against the flow
demand as originally *derived* pre-bomb, and against whatever flows *survived*
post-bomb — so deleting a machine deleted its unroutable flows from the
denominator and the gate went **up**. Measured on the quick profile: a crater
that destroyed 3 machines moved feasibility 96.6% → 96.8% and regret came out
0.0000. `_zpf_flow_demand()` holds the denominator at the pre-bomb demand: a
flow whose endpoint was destroyed is not "no longer required", the material
genuinely stops moving.

**Spawned depots could substitute for lost machines.** `_feasibility_breakdown`
counted `len(res["placed"])`, which after recovery also holds any depots
`repair_feasibility` spawned. Recovery results now carry `placed_count`, the
count of original machines only.

**The pre-bomb rate was not comparable to anything downstream.** The recovery
pipeline re-lays every belt at once on a fresh grid; the pre-bomb layout's belts
were laid incrementally by `blf_decode` → ALNS → Tabu → `connect_or_remove` →
`repair_feasibility`, each into whatever space the last one left. Those are not
the same procedure. On the pool fork the un-recovered post-bomb layout scored
**6.20 against a pre-bomb 3.17** — destroying two machines appeared to double
the factory's revenue, purely because a less congested grid routed flows the
incremental process never managed.

`post_bomb_state(base, None)` is the same layout with no crater, put through the
same fresh-grid re-route. Phase 4 computes it once per layout and prints it, so
the damage decomposes:

```
reroute = ref  - pre      nothing to do with the bomb
damage  = post - ref      what the crater cost
gain    = rec  - post     what the recovery contributed
```

**On `_pool` the re-route term dominates regret entirely.** Measured, quick
profile:

```
Layout #1  pre-bomb Rate=13.8053
           clean re-route reference: Rate=4.4516   re-route effect -9.3537
           REGRET over 3 scenarios: mean=9.3596  worst=9.3891
```

Regret is 9.36 and the re-route alone accounts for 9.35 of it. **Essentially the
whole reported regret on this fork is the difference between two belt-laying
procedures, not the bomb.** On `_fixed` the same term is usually 0.0000 and
occasionally ~1.15, because those layouts are small enough to route fully both
ways — which is exactly why this went unnoticed.

This is a decision, not a patch, so it is left open: either **report regret
against `ref` instead of the pre-bomb rate** (a one-line change in Phase 4, but
it redefines the thesis's headline metric), or **put the pre-bomb layout through
the same re-route** before quoting it. Doing neither means quoting a regret that
is mostly an artefact. See "Still open".

Phase 4 also counts, and warns about, scenarios where the un-recovered post-bomb
layout scores **higher than the reference** — a modelling defect by definition,
and previously invisible because regret clamps at zero.

---

## R5 — The recovery optimises a different objective from the one regret measures — **NEW, OPEN, and now the most important item**

Only visible because R1 gave us a baseline to compare against, and it shows up
immediately once you look:

```
Layout #2  pre-bomb Rate=9.9956,  clean re-route reference 8.8465
      # 1 crater(19,39)  rate  9.9956 ->  8.7614 ->  8.2501   gain=-0.5113  frac= n/a
      # 2 crater(41,53)  rate  9.9956 ->  8.8039 ->  8.4808   gain=-0.3231  frac= n/a
      # 3 crater(47,59)  rate  9.9956 ->  2.8000 ->  8.8039   gain=+6.0039  frac=99.3%
```

In two of three scenarios `gain` is **negative**: the recovered layout scores
worse than the un-recovered one. That is not a bug in the recovery — it is doing
exactly what it was told. (`frac` reads `n/a` on those two because the crater
cost less than 1% of the reference, so a "fraction recovered" would be a
division by noise; the sign of `gain` is the signal.)

**The mismatch.** `zpf_recovery` selects on `(unrouted, mhc + zone_penalty +
relocation_penalty)`, with `feasible` as a tiebreak. Phase 4 reports
`revenue × feasibility`. Those are different functions of the same layout: the
search will happily trade revenue for a shorter belt or one fewer unrouted flow,
because revenue is not in its objective at all. Scenario 3 above shows the
search working well when the two happen to align (2.80 → 8.80); scenarios 1 and
2 show them pulling apart.

This was invisible before, because regret clamps at zero and there was no
un-recovered baseline to notice the recovery had gone backwards from.

**Why it matters.** "NSGA-II recovery beats SA recovery" is a claim about
recovering *throughput*. If neither search optimises throughput, the comparison
measures which one is better at minimising belt length under a disruption — a
defensible research question, but not the one the thesis asks, and the two
answers can differ in sign.

**Options.**

1. **Put the reported quantity in the objective.** Add `-terminal_rate` as a
   third NSGA-II objective and fold it into the SA's scalar cost. Clean for the
   GA (the non-dominated sort is already generic over the number of objectives);
   the SA needs a scalarisation weight, and MHC is in the hundreds-to-thousands
   while terminal_rate is 0–10, so that weight has to be stated and justified
   rather than picked.
2. **Report against the recovery's own objective** — quote
   `mhc + penalties` and unrouted-flow counts as the recovery result, and treat
   the rate as a secondary observation. Honest, requires no code, and changes
   what the results chapter claims.
3. **Keep both and report the divergence** — it is itself a finding: a recovery
   optimised for handling cost does not necessarily restore throughput.

**Whichever is chosen, it must be applied identically to both variants** — that
is the invariant R3 established, and giving only the GA a third objective would
break the comparison outright.

This is a design decision, not a defect to be silently patched, so it is left
open deliberately.

---

## P8 — Post-bomb visualisation was not comparable — **FIXED**

Phase 6 called `derive_flow_matrix(post_bomb_placed)` from scratch to build the
middle panel, so the panel showed a different greedy matching rather than the
damaged layout. It now uses the `post_bomb_state` object Phase 4 already scored.

---

## P6 — `sustain` penalised keeping machines — **FIXED**

`sustain_ratio = SIM_EQ_MAX_TICKS / chain_time`, and `chain_time` is the
critical path. Keeping *more* machines lengthens it, so a better-repaired layout
scored worse on this gate (0.76 → 0.22 in the P4 table below). This is most of
why the `_pool` fork reported the bomb *improving* the factory in 4 of 4
layouts: routing got worse, `sustain` improved by more.

**Two changes.**

`_chain_stats()` replaces `_chain_time()`. It returns `time` (the critical path
including belt travel) and `ideal` (the same path with every belt treated as
instantaneous — the part the layout cannot do anything about, set by the recipe
chain). `_sustain_budget(chain_ideal)` scores against
`CFG.SUSTAIN_SLACK × chain_ideal` rather than a flat tick count, so removing a
machine shortens numerator and denominator together and the gate measures what
the **layout** adds: belt travel, detours, congestion. `CFG.SUSTAIN_NORMALISE =
False` restores the old rule.

**Cycles are no longer an artefact of an iteration count.** The old cycle
fallback relaxed the leftover nodes `min(len(remaining), 10)` times with no
convergence test. `arrival` grows monotonically along a cycle and never reaches
a fixed point, so the reported `chain_time` for any cyclic layout was a function
of that `10` and nothing else — change it and the sustain gate changes. A
longest path is not defined on a cyclic graph, so each strongly connected
component is now contracted (Tarjan, iterative) into one node weighted by its
members' process times plus its internal belt travel — one lap of the loop — and
the longest path is taken over the condensation, which is a DAG by construction.
Reduces to the old answer on acyclic layouts.

---

## P5 — The power gate was binary — **FIXED (option 3)**

With one thermal bank `power_ratio` is 1.00 or 0.00 — the bank is fuelled or it
is not. Under an equal-weighted mean that made one belt landing or missing worth
25 feasibility points, more than any other single fact about the layout, and
whether it lands is close to arbitrary since it competes for `main_unit`'s six
output ports with everything else.

`CFG.W_POWER = 0.0`. The gate is **not** gone: `power_ok` is still computed,
still printed in the per-gate breakdown, and still part of the hard `feasible`
boolean. It is no longer allowed to dominate a graded score it cannot vary
smoothly. `_feasibility_ratio` now drops zero-weight gates rather than averaging
them in, so the remaining three renormalise to a third each.

Option (4), a dedicated fuel depot so the belt reliably lands, remains the
physical fix and is still open.

---

## P4 — Feasibility aggregation flattens everything — **FIXED (reported + selectable)**

`_feasibility_ratio` was an equal-weighted mean of four ratios, so any single
gate hitting 0 cost exactly 25 points regardless of the other three:

```
 phase placed removed flows routed | place route power sust | FEAS
    P1     16       2    23     14 |  0.89  0.61  1.00  0.76 |  81%
    P2     18       0    27     23 |  1.00  0.85  0.00  0.22 |  52%
```

Phase 2 placed more, pruned fewer, routed a higher fraction — and scored 29
points lower.

`CFG.FEAS_AGGREGATION` selects `"mean"` (default, unchanged), `"geometric"` (a
weak gate hurts multiplicatively instead of costing a fixed slice) or `"min"`.
The breakdown is printed everywhere the headline is. Combined with P5 and P6,
the two gates that actually misbehaved are dealt with, so the mean is now
defensible as a default rather than merely conventional.

---

## P3 — The 0.01 efficiency cascade — **PARTIALLY FIXED**

`_calculate_revenue` multiplies a machine's efficiency by **0.01** for each
unrouted input, takes the `min` across inputs, and propagates downstream, while
`route_ratio` counts broken flows linearly. The two disagree by construction:

```
  BOM  flows  revenue |  worst 1 break   worst 2   worst 3
   14     14     4.00 |           -12%      -12%      -12%
   24     24     8.00 |           -43%      -50%      -56%
   34     30     9.03 |            -5%      -11%      -16%
```

One broken flow can cost 43% of revenue while `route_ratio` moves 4 points.

**Done:** promoted to `CFG.STARVED_INPUT_EFF`, documented as the knob it is —
it, not the gates, sets how brutally the search is punished for an unrouted
upstream flow, and `terminal_rate = revenue × feasibility` is the objective.

**Not done:** option (1), making the penalty proportional to the fraction of
required input actually delivered. That needs the per-tick rate information the
`_pool` fork's `derive_flow_matrix` now carries and the `_fixed` fork does not.
It is the right fix and it is now unblocked on `_pool`.

The cascade is still visible in results: on the SA `_pool` quick profile a single
destroyed machine takes the rate from 10.11 to 3.20. That is the cascade, not
the crater.

---

## P2 — Revenue double-counted intermediates — **FIXED (option 2, not option 1)**

`_calculate_revenue` credited every machine's output at production regardless of
destination, and `REVENUE_TABLE` prices intermediates (`steel_part` 3,
`ame_bottle` 2, `ferri_part` 1, `ame_part` 1, `ori_crust` 1), so a part earned
revenue *and* the product built from it earned revenue again:

```
target=buck_cap_A  gross 14.00 |  buck_cap_A 100%
target=SC_bat      gross  8.00 |  SC_bat  75%  +  ferri_part  25%
target=HC_bat      gross 11.40 |  HC_bat  47%  +  steel_part  53%
```

A battery burned by a thermal bank likewise earned full revenue *and* supplied
power. Ranked by terminal-rate-per-machine, `can_cit_A` came **last** despite
tying for the highest unit revenue, while the three batteries took the top three
places — the exact inversion of what the model is supposed to express.

**Option 1 (credit only what reaches an `io_sink`) was implemented first and
rejected on measurement.** It makes revenue hinge on whether one particular belt
routed: on the SA quick profile layout #2 scored 2.6273 pre-bomb and **0.0251**
after nothing more than re-routing the same undamaged layout on a fresh grid.
Under the `_fixed` fork's 1:1 greedy matching a product reaches a sink through a
single Stage-3 flow with a round-robin sink assignment, so the objective goes
near-binary on one A\* result. The register already anticipated this — option 1
"interacts with P1" — and the interaction is fatal at this pairing quality.

**Option 2 is the default:** `CFG.REVENUE_MODE = "net"` credits produced minus
consumed per material. A material the factory consumes itself nets against its
own production, so it is paid for exactly once, at the point it stops being an
input to something. Structural, and it does not depend on which belts routed, so
it degrades smoothly. `"sink"` and `"gross"` remain available; `"sink"` is worth
revisiting on `_pool`, where Stage 3 deposits every unallocated supply by rate
rather than through one greedy match.

---

## P7 — Rotation was never searched — **FIXED**

Every chromosome was built `Gene(m.id, Rotation.R0, r)` — in `evaluate_nsga2`,
in Phase 2 and in `zpf_recovery`. Since rotation decides which face carries the
I/O ports, an entire dimension of the layout problem was fixed at zero.
`greedy_rotation_search` existed in the legacy appendix and was called by
nothing; at 4 × n_genes × passes full evaluations it is unaffordable at
`MAX_MACHINES = 160`.

Two contained fixes:

- **Recovery.** Rotation is part of the solution and `ZPFNeighbourhood`'s
  `rotate` operator searches it. This is where the thesis makes its claim, and
  it is also where port facing matters most — after a bomb, a machine's old
  orientation may no longer face anything.
- **Layout.** `rotation_polish()` is a budgeted greedy pass in Phase 2 over the
  `CFG.ROTATION_POLISH_TOP` machines carrying the most handling cost. It accepts
  a rotation only if it improves the **same criterion Phase 2 ranks candidates
  on** (`_calculate_weighted_score`, i.e. feasibility-dominated, with MHC
  breaking ties) *and* costs no more than
  `CFG.ROTATION_POLISH_MHC_TOLERANCE` more MHC than the incumbent. It therefore
  cannot make a candidate worse by the phase's own measure.

  The MHC bound is not cosmetic. Without it the pass accepted a rotation that
  bought 2.4 points of feasibility for **+386 MHC (625 → 1011, +62%)** — MHC is
  one of the three NSGA-II objectives and Phase 2's Tabu pass exists
  specifically to cut it, so an unbounded rule quietly undoes Tabu. Phase 2's
  ranking score has no MHC term at all, which is why the bound has to be
  explicit rather than emergent.

`ROTATION_POLISH_TOP = 0` disables it. `ROTATION_POLISH_MAX_BOM` skips it on
layouts where it would dominate the phase.

---

## P9 — Smaller open items — **ALL FIXED**

- **`singleton` was only read in recovery** and nothing asserted the invariant it
  relies on. The catalogue cell now asserts exactly one singleton machine type
  and that every boundary machine exists. `_zpf_place`'s "hub first" ordering is
  only correct under that invariant.
- **Destroyed `edge_only` machines could not return** — no grid edge exists
  inside a crater in the middle of the factory, so a bombed depot was
  permanently lost. `CFG.ZPF_EDGE_RELOCATION` lets it return to any edge.
- **`route_belts`' fallback returned the first working out-port's best path**,
  not the shortest over the port pairs, despite the docstring. It now keeps
  searching across out-ports — **within a cap**, because the fallback is reached
  on exactly the flows a congested layout has most of and the full product is
  |outs| × |ins| A\* searches per flow (6 × 14 = 84 for a 9×9 `main_unit`, on a
  70×70 grid, inside every ALNS iteration and every recovery evaluation).
  Uncapped it took the quick profile from ~300s to ~4600s on the pool
  notebooks. `CFG.ROUTE_FALLBACK_MAX_PAIRS` states the budget and the docstring
  now promises "shortest over the pairs tried".
- **Repair-added `FlowPair`s used `intensity=1.0`** — and, worse, a repair of an
  *existing* unrouted flow appended a **duplicate** `FlowPair` instead of marking
  the original routed, so `flows_total` grew by one on every repair while the
  original never went away. `repair_feasibility` now hands the existing pair
  back and `apply_repair_belts()` marks it routed in place; genuinely new
  connections carry the destination's real per-tick demand.
- **Doc drift** — see N1: the "50×50" was not stale documentation.

---

## R0 — The disruption often did not disrupt anything — **FIXED (and now in `_pool` too)**

`make_bomb_scenarios()` draws crater positions uniformly over the grid and
**rejects** any that destroy nothing, repeating until `CFG.ZPF_SCENARIOS` valid
scenarios are found. Phase 4 runs every scenario and reports the regret
distribution. The scenario set is seeded from the **layout**, so GA and SA face
identical craters.

```
Layout #1  pre-bomb Rate=1.8961, Feasibility=87.8%
  # 1 crater( 9,38)  destroyed=1 movable=10  post Rate=1.7000 feas=78.7%  regret=0.1961
  # 5 crater( 1,11)  destroyed=1 movable= 9  post Rate=1.8098 feas=83.8%  regret=0.0863
  # 6 crater(38,41)  destroyed=1 movable= 9  post Rate=1.4796 feas=88.9%  regret=0.4164
  # 8 crater(51,32)  destroyed=1 movable= 7  post Rate=1.7925 feas=83.0%  regret=0.1036
  REGRET over 10 scenario(s): mean=0.2441  median=0.1961  worst=0.6448  zero-regret=0/10
```

Knobs: `ZPF_SCENARIOS` (10), `ZPF_REQUIRE_DAMAGE` (True), `ZPF_SAMPLE_ATTEMPTS`
(4000). `ZPF_SCENARIOS = 1` restores the old single-bomb behaviour.

**New this session:** ported to `_pool`, whose Phase 4 was still firing a single
bomb at `CFG.ZPF_X/ZPF_Y`.

**Cost note.** Phase 4 is N× more expensive, plus one extra re-route per
scenario for R1's baseline. Prefer more scenarios over a deeper search per
scenario — 20 samples at 100 iterations tells you more about resilience than 1
sample at 620.

---

## R0b — Layout compactness and routability are in direct tension — **CHARACTERISED; knob added**

Layouts occupy 4–11% of their own bounding box. The cause is `blf_decode`: a
machine with no already-placed topology neighbour skips the adjacency spiral and
takes the shuffled whole-grid fallback, landing anywhere; 3–13 machines per
layout do this and each becomes a random seed point.

**But compacting makes routing worse.** Prototype replacing the shuffled
fallback with a spiral anchored on the layout centroid:

```
 rate           variant  placed     bbox   fill   routed  route%      MHC
 0.25    current (sp=1)      34    66x70     9%    30/40     75%     1466
           compact sp=1      34    46x41    21%    20/40     50%      961
           compact sp=2      34    47x44    19%    25/40     62%     1330
           compact sp=3      34    45x45    19%    28/40     70%     1483
```

MHC falls 30–40% and routing falls with it, roughly proportionally. The sparsity
is not a defect costing routing — it is what *enables* the current routing rate.
Compactness and routability cannot both be improved by tuning the existing
scheme; that needs a structured row/aisle generator with reserved belt
corridors, which is a new placement algorithm and out of scope.

The register's recommendation was to scale the disruption to the layout instead.
R0's rejection sampling does the necessary part. The optional part —
scaling the crater and radii with the layout's extent — is now
`CFG.ZPF_SCALE_TO_LAYOUT`, **off by default** because turning it on moves every
downstream number:

```
 rate machines  crater   r1   r2  destroyed  movable  % hit
 0.25       30     3x3    5   12        1.0      8.0    27%   <- default
                   5x5   10   20        1.6     11.2    38%
                   7x7   13   26        1.8     14.1    47%
 0.40       40     3x3    5   12        1.0      6.8    17%   <- default
                   5x5   10   21        1.8     14.9    37%
                   7x7   14   28        2.2     22.2    55%
```

Running it as a sensitivity sweep — "does the recovery result hold as the
disruption grows?" — is a stronger claim than one crater size, and it is now a
one-line experiment.

---

## R2 — The logistics network is not modelled — **FIXED IN `_pool`; one part is unfixable**

**The intended model** (confirmed with the author): material deposited into any
stash, depot_loader or main_unit input is available from any depot_unloader or
main_unit output. One global pool, transfer instant and free. Depot loaders and
unloaders are edge-only; stashes may sit anywhere.

The `_pool` fork implements it: rate-aware Stage 1 matching, Stage 2 withdrawal
from the nearest pool source, Stage 3 deposit at the nearest pool sink, real
per-tick `intensity`, and `pool_balance()` reporting per-material
deposited/withdrawn/deficit. **This fork is the R2 fix**; `_fixed` retains the
old model deliberately, as the comparison baseline.

**Batteries are now produced.** `derive_rate_balanced_bom` feeds thermal-bank
fuel demand back through the expansion as a fixed point
(`CFG.SELF_FUEL_POWER`), so the factory manufactures the batteries it burns
instead of drawing them from nothing. A self-fuelling factory is 50–130% larger,
which is a principled increase in layout complexity with a real production chain
behind it.

**Pool conservation is now reported.** An internal material cannot be withdrawn
unless something deposited it, and nothing checked: a real run showed
`utility_supply: deposited 0.0, withdrawn 1.0`. Phase 2 prints any deficit.
Whether it becomes a hard gate is still open.

### The part that cannot be fixed as specified

`database.xlsx` prices machines in its `machine_mat` column, and that column
covers **production machines only**. There is no build cost in the source for
`stash`, `depot_loader` or `depot_unloader`; the `rules` sheet prices their
*power* ("all utilities use 10 power each except batteries, belts, depot
unloader and loader") and says nothing about construction. So "replace the
placeholders with the real figures from `database.xlsx`" cannot be done — there
are no such figures.

`CFG.LOGISTICS_BUILD_COST` is therefore an **analogy**, and is now labelled as
one: a stash is 3×3, the same footprint class as the Refining / Shredding /
Fitting / Moulding units, which the database prices at 5–10 units of an
early-chain material; the depots get half a stash on the grounds that they are
edge-only and hold nothing. This needs a sentence in the methodology chapter.
`LOGISTICS_BUILD_COST = ()` makes them free, which is what the source model
literally specifies.

---

## P1 — The BOM and the flow matrix are two incompatible models — **FIXED IN `_pool`; open in `_fixed`**

`derive_rate_balanced_bom` sizes machines by *throughput*; `derive_flow_matrix`
in the `_fixed` fork wires them by *discrete one-to-one pairing* — Stage 1 keys
`matched_demands` on `(material, consumer_id)` and `break`s after the first
supplier. Rate information is discarded entirely.

`SC_bat` at rate 0.3 builds 6 refining, 6 fitting, 9 shredding, 3 packaging. Two
fitting units per packaging unit is correct arithmetic. The `_fixed` flow matrix
wires one each and orphans three into `main_unit`, so each packaging unit gets
half the input it needs and three fitting units have no production role.

The `_pool` fork's Stage 1 matches **by rate**: a consumer keeps drawing from
further producers until its per-tick demand is met. That is the register's
option 3, and with Stages 2/3 it is most of option 4.

**`_fixed` is left as-is deliberately** — it is the baseline the pool fork is
compared against, and changing both defeats the comparison. It should be
described as a limitation of that fork, not as a bug awaiting a fix.

---

## G1 — GA search quality — **FIXED (and now in `_pool` too)**

Three defects: the population collapsed (20 Phase-2 candidates, 9 distinct
layouts); the GA could not inherit placement (one uniform crossover preserved 5%
of the placement order at `MAX_MACHINES=160`, so 70% of the genome was noise);
and destroying a machine could raise revenue (`min()` over *surviving* inputs).

All three were fixed in `_fixed` previously. **The `_pool` fork was branched
before that work and had silently lost all three**, plus R0. Ported this
session:

- `_calculate_revenue` scores efficiency against the recipe's **required**
  inputs, so an input no routed flow supplies always counts as
  `CFG.STARVED_INPUT_EFF`. This is a direct cause of the pool fork's
  `regret = 0.0000`.
- the `MAX_MACHINES` priority tail is gone from `init_individual`,
  `evaluate_nsga2` and Phase 2; build order comes from `_order_instances`.
- candidates are de-duplicated by `genotype_key()`.
- `make_bomb_scenarios` / `scenario_damage` and the scenario-set Phase 4.

---

## N1 — The grid is 70×70; the source model specifies 50×50 — **NEW, OPEN**

Found while chasing the "50×50" doc drift in P9. `database.xlsx`, sheet `rules`,
states *"The total area for the map is 50x50"*. The notebooks run **70×70**.

The markdown was not stale — it was the specification, and the code is what
drifted. Nothing in the code assumes either size (every reference goes through
`GRID_W`/`GRID_H`), but 70×70 is **1.96× the specified area**, which makes
placement easier and routing much easier, and R0b established that routing
success in this model is largely a function of how much empty space there is.

Every number in the results chapter is computed on that larger board.

**Options.** Justify the enlargement explicitly in the methodology chapter (the
BOMs at `MAX_MACHINES = 160` genuinely do not fit on 50×50 — grid capacity tops
out around 190 machines at 70×70, so roughly 95 at 50×50); or set
`GRID_W = GRID_H = 50`, cap `MAX_MACHINES` accordingly and re-run. Doing
neither is not an option — a reader with the database in hand will notice.

Two other `rules` lines are worth checking against the catalogue while you are
there: the power schedule ("3x3 machines cost 10 power each, 4x_ cost 20, above
those 30") and "Main unit is a 9x9 machine, with 3 output nodes on north and
south sides".

---

## Still open

**Methodology — decide these before the next full run**

These two together decide whether the results chapter's headline number means
what it says. Neither is a defect to patch — both are choices only the author
can make — so both are left as they are.

- **R5 — what the recovery optimises.** It searches
  `(unrouted, MHC + penalties)` while the results report
  `revenue × feasibility`. Measured: the recovered layout scores *worse* than
  the un-recovered one in 2 of 3 scenarios on one quick-profile layout. Pick
  option 1, 2 or 3 above and apply it to **both** variants.
- **What regret is measured against.** On `_pool`, 9.35 of a regret of 9.36 is
  the clean-re-route effect rather than the crater (see R1). Either report
  regret against the reference state, or put the pre-bomb layout through the
  same re-route before quoting it.

**Modelling**

1. **N1** — grid size versus the source specification. Decide and document.
2. **P3 option 1** — shortfall-proportional starvation penalty instead of a flat
   `STARVED_INPUT_EFF`. Unblocked on `_pool` now that flows carry real rates;
   this is what makes a single destroyed machine stop costing two thirds of the
   factory's rate.
3. **P5 option 4** — a dedicated import depot for thermal-bank fuel, so the
   power gate is decided by the layout rather than by port contention.
4. **P1 in `_fixed`** — left deliberately; describe as a limitation.
5. **Pool conservation** — decide whether a `pool_balance` deficit becomes a hard
   gate or stays a report.

**Pool-fork tuning** (from `POOL_REWORK_STATUS.md`, still open)

6. **Stashes are barely used** — 7 built, 7 with no flow at all. Rate-aware
   Stage 1 satisfies internal demand directly, so little surplus is left to
   deposit. `EXPORT_STASHES = 0.15` over-provisions; size it from the number of
   Stage-3 deposit flows instead of from BOM size. Now that logistics machines
   cost something, unused stashes are paid for.
7. **Withdrawal flows route badly** — 9/20 withdrawals routed against 26/38
   direct flows. Depots are edge-only so they sit on the boundary while
   consumers are in the middle. Worth trying: more, smaller depots; or letting a
   machine withdraw from *any* source rather than only the nearest.

**Experiments the fixes make possible**

8. `ZPF_POSITION_SEARCH = False` versus `True` — how much does the metaheuristic
   contribute over the deterministic repair? This is now measurable and is a
   result in its own right.
9. `ZPF_SCALE_TO_LAYOUT` sweep — does the recovery result hold as the disruption
   grows from ~1 machine to half the factory?
10. `FEAS_AGGREGATION` and `REVENUE_MODE` sensitivity — do the conclusions
    survive a different aggregation rule and a different revenue attribution?

---

## Verification

Quick profile, all four notebooks: **0 execution errors**, every phase emits its
output.

### What a quick run does NOT cover

Worth stating, because "the quick profile passes" is weaker evidence than it
looks:

- **B1's early stop is compiled but never taken.** `_QUICK_ZPF` caps the budget
  at 18–20 evaluations and `ZPF_EARLY_STOP` is 100, so a quick run can only ever
  reach `stopped_early=False`. The branch was exercised separately by running
  copies of both `_fixed` notebooks with `ZPF_EARLY_STOP=4` forced through
  `_QUICK_ZPF` — see below. **Any future change to the stopping rule needs the
  same treatment**; the default profile will not catch a fault in it.
- **B1's budget values themselves are not exercised.** `ZPF_ITERATIONS = 300`,
  `ZPF_SCENARIOS = 5` and `PHASE4_TOP_N = 5` are all overridden by the quick
  profile. They take effect only at `RIGOUR = "full"`.
- **Solution quality, at all.** `POP_SIZE`/`NGEN` are far below what NSGA-II
  needs and the terminal-rate band is narrowed to keep BOMs tiny.

Three invariants are now asserted at runtime rather than claimed:

- **Catalogue** — exactly one `singleton` machine type, and every boundary
  machine (`IO_SOURCE_IDS`, `IO_SINK_IDS`) exists. `_zpf_place`'s hub-first
  ordering is only correct under the first.
- **Crater integrity** — `crater_violations()` is asserted on the post-bomb AND
  post-recovery state of every scenario: no machine footprint and no belt tile
  may intersect the crater. Previously this was a one-off manual check; a
  regression in the placement or routing path would not have surfaced as an
  error. Phase 4 prints the count of states checked.
- **Pool conservation** (pool fork) — Phase 2 prints any material withdrawn from
  the logistics pool that nothing deposited.

Runtime, quick profile, run against the CURRENT notebooks (i.e. including B1's
budget change), four in parallel:

```
GA _fixed   140.6s  0 errors  crater 12/12      SA _fixed   183.5s  0 errors  crater 12/12
GA _pool    303.2s  0 errors  crater 12/12      SA _pool    321.2s  0 errors  crater 12/12
```

Note these supersede an earlier round run against the pre-B1 file state. When
the notebooks change under a run, its result is evidence about a file that no
longer exists — the whole set was re-run rather than reported across two
versions.

Two unit checks were run outside the notebooks, since both replace load-bearing
arithmetic:

- `_chain_stats` on synthetic graphs — a simple chain, a branch where the
  longest path must win, a 2-cycle (finite and independent of any iteration
  count), an empty graph, and an unrouted flow. All correct.
- the net-revenue rule — the two-fitting-units-to-one-packaging-unit case
  (`gross 1.800 → net 0.800`, the double-counted `ferri_part` netting to zero),
  a battery burned by a thermal bank (`0.120 → 0.000`), and a genuine surplus,
  which is still paid.

The quick profile proves the plumbing. It says nothing about solution quality —
`POP_SIZE`/`NGEN` are far below what NSGA-II needs and the terminal-rate band is
narrowed to keep BOMs tiny. **Never quote numbers from a quick run.**

### Two things the quick runs surfaced that are not yet resolved

- **R5**, above. The headline item.
- **The pool fork still shows the bomb improving the layout in 1 of 3
  scenarios**, now measured against the re-route reference rather than against
  the pre-bomb rate. Down from 4 of 4, but not zero. The remaining cause is most
  likely the starvation cascade (P3): with `STARVED_INPUT_EFF` at 0.01, removing
  a machine that was dragging a chain's efficiency down can pay for itself.
  P3 option 1 is the fix and is unblocked on this fork.
