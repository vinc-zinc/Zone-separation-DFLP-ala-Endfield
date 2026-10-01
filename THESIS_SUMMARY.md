# Thesis summary — alignment with Chapters 1–3 and what Chapter 4 needs

Prepared against `Thesis_Chapters1-3_Final_Progressive_Humanized_Fixed.docx` and
`Thesis/Dissertation Handbook v2.0`. Handbook §8.6 requires the body to contain
(i) introduction and background, (ii) detailed description of the study
including theories, models, methods, (iii) data collection and analysis
techniques, (iv) main results and discussion, and (v) conclusions and
significance. Chapters 1–3 cover (i)–(iii). **Chapter 4 (Results and Discussion)
and Chapter 5 (Conclusion) are outstanding.**

---

## PART 0 — Research question completion status

| RQ | Subject | Machinery | Valid evidence | Gap |
|---|---|---|---|---|
| RQ1 | Encoding a localised disruption; evaluating pre/post difference | complete | **none yet** | both full runs predate the fixes that made the evaluation sound |
| RQ2 | Recovery quality **and convergence speed** under ZPF | complete | **none yet** | GA and SA have never been run on the same layouts; speed never measured |
| RQ3 | Profit-driven vs robust layout | **absent** | none | no robust archetype exists; the dispersion lever also washes out at scale |
| RQ4 | Sandbox validity and repeatability | complete | **strong** | needs a formal repeatability experiment to be quotable |

### RQ1 — encoding and evaluation

**Implemented and sound.** Four-zone ZPF with majority-of-cells membership, the
crater as an impassable A\* obstacle, zone-occupancy and avoidable-relocation
penalties, gate-level pre/post reporting, and rejection-sampled scenario sets.

**But no run yet demonstrates it.** Both full runs predate three fixes that the
evaluation depends on: `ZPF_PRESERVE_FLOWS` (without it the post-bomb graph is a
different greedy matching, not a damaged one), monotone efficiency (without it
destroying a machine could *raise* revenue and drive regret to 0.0000), and
scenario sets (both runs bombed each layout once, at a fixed coordinate).

*To close:* one full run per variant on the current code with scenarios enabled.

### RQ2 — recovery quality and convergence speed — **largest gap**

The two full runs cannot be compared:

```
GA full : NGEN=30, ZPF budget=620, pre-bomb rates 19.26 / 21.08 / 13.13 ...
SA full : NGEN=50, ZPF budget=500, pre-bomb rates 13.39 / 20.42 / 14.93 ...
```

Different seeds, different generation counts, different recovery budgets, and
therefore **completely different pre-bomb layouts**. A recovery comparison
requires both algorithms to repair the *same* damaged factory; nothing in the
folder does that.

Convergence speed — half of what RQ2 asks — has never been measured at all:

- the GA recovery logs 70 convergence lines; **the SA recovery logs none**
- no temperature or acceptance trace exists for the annealing schedule
- no wall-clock time or evaluation count is recorded anywhere

*To close:* identical `RANDOM_SEED`, `NGEN`, `ZPF_ITERATIONS` and scenario sets
for both variants; add convergence logging to the SA loop (best-cost per
iteration, acceptance rate, temperature); record evaluations-to-best and
wall-clock per recovery. Then report solution quality and convergence as a
paired comparison over the same layouts and craters.

### RQ3 — see A5. Not implemented, and the obvious lever does not work at scale

Beyond having no robust archetype, spatial dispersion is a weak lever at the
sizes actually run. Measured across BOM sizes:

```
   BOM  placed     bbox   fill  grid used | destroyed  movable  % layout hit
    24      24    64x70     7%         6% |      1.15      6.0           25%
    93      93    70x70    23%        23% |      1.20     10.8           12%
   179     179    70x70    43%        43% |      1.32     17.4           10%
   294     223    70x70    50%        50% |      1.45     19.8            9%
```

Every layout spans the whole grid; only density varies. And `% layout hit`
*falls* with size, because the r2 = 12 zone covers a fixed ~9% of a 70×70 grid —
at full-run scale every layout loses roughly 10% of its machines regardless of
how it was built. A dense-versus-dispersed comparison would show almost no
difference at the sizes being run.

*Options:* scale the disruption with the layout so dispersion matters again
(also required by R0); or change the robustness dimension to **redundancy**
(same target rate, deliberately over-provisioned BOM — a one-line contrast
against `derive_rate_balanced_bom`'s minimum); or re-scope the question.

### RQ4 — strongest, and nearly complete

Validity evidence exists and is independent: a layout scored 98.7% by the static
model reached equilibrium at tick 280 in the discrete-event simulation, ran 98%
of its machines, and never browned out, with static and simulated Gate 2 in
agreement. The disagreement detector is itself a result — it characterises when
the static critical-path estimate is optimistic.

Repeatability is fixed and verified: layout decoding draws from a threaded RNG,
and the per-genotype seed uses `zlib.crc32` rather than Python's per-process
salted `hash()`. Before this, the same chromosome decoded differently in every
interpreter session.

*To close:* a short formal experiment — N runs at a fixed seed showing identical
outputs, and N runs at differing seeds quantifying variance in the reported
metrics. Cheap to produce and it converts a claim into a measurement.

---

## PART A — Corrections needed in Chapters 1–3

These are places where the written methodology no longer matches the
implementation. Each is the kind of discrepancy an examiner can check directly
against the code.

### A1. Grid size — §3.5 states 150×150; the implementation is 70×70

`GRID_W = GRID_H = 70` in the Control Panel. Every result in the folder was
produced on 70×70. Either correct the text or re-run at 150×150 — but note the
grid is **not** currently the binding constraint (a 137-machine BOM places fully,
using 81% of the grid including clearance; 225 machines fails at 132%), so
enlarging it would change the saturation ceiling, presently around 190 machines.

### A2. Generations — §3.5 states 100 generations

The completed full runs were **100 × 50** (SA) and **100 × 30** (GA). State the
figures actually used, per run.

### A3. Objective count — §3.5 states four objectives including Regret

The evolutionary loop now optimises **three**: build cost ↓, terminal rate ↑,
MHC ↓. Regret was removed from the objective vector because it is by
construction a *post-disruption* quantity — Phase 1 generates layouts, Phase 4
bombs them, so during evolution regret was pinned at 0.0 and merely gave NSGA-II
a constant axis on which every individual tied, inflating the non-dominated
front and diluting selection pressure on the three measured objectives.

This is defensible and worth stating explicitly as a design decision, not an
omission. Regret is still computed and reported in Phase 4.

### A4. Crossover — Objective 1 states "Pair Wise Exchange crossover"

The operator named `pwx` performs **uniform crossover** at p = 0.5, not pairwise
exchange. Either rename the operator or correct the objective.

More substantively, the encoding has changed. The genome previously carried
`MAX_MACHINES` float "priority" genes that determined build order. Measured, one
uniform crossover preserved only **5%** of the resulting placement order at
`MAX_MACHINES = 160` — 70% of the genome was noise that could never be
inherited. Build order is now derived deterministically from the production
graph, and arrangement is delegated to ALNS/Tabu in Phase 2. Genome: 227 → 67
genes. **§3.4 and Objective 1 need updating to describe this encoding.**

### A5. Objective 4 / RQ3 — no implementation found

> *"To compare the systemic resilience of a profit-driven layout and a spatially
> dispersed robust layout…"*

No code in this folder generates a "spatially dispersed robust" variant. The
`_robust` notebooks differ from their siblings by structural reordering, not by
any dispersion mechanism. **This objective and RQ3 are currently unanswerable.**

Options: implement a dispersion-biased variant (e.g. a spacing or spread term in
the objective); re-scope RQ3 to compare layouts that the existing search already
produces at different points on the Pareto front (high-rate/dense versus
low-rate/sparse); or drop it. This is the single largest gap between the stated
objectives and what exists.

### A6. ZPF zone membership — §3.1 should state the rule

Zone assignment is by **majority of a machine's cells**, not its centre point: a
machine belongs to a circle when strictly more than half its footprint lies
inside (for a 3×3, at least 5 of 9). Machines therefore need not lie strictly
within a zone to belong to it.

Also, §3.1 says machines far from D "incur prohibitive relocation penalties that
effectively prevent their movement". In the implementation the stable zone is
**strictly immovable**, not penalised. State whichever you intend.

### A7. Relocation cost — the penalty term should be described as implemented

Two distinct costs are applied, and the write-up should separate them:

- **Zone-occupancy penalty**: `5 × distance` for machines finally in the penalty
  ring, scaling with distance from the blast.
- **Avoidable-relocation penalty**: `PENALTY_PER_MOVED_MACHINE × (1 + d/r₂)` for
  every machine that moved but did not have to. Machines destroyed by the crater
  are exempt, since they had no choice.

Before the second term existed, the search was rewarded for disturbing
undamaged neighbours — the only cost of moving one was an incidental change in
the occupancy term, which *shrinks* toward the blast.

---

## PART B — Methods material to add to Chapter 3

Present in the implementation, absent from the written methodology.

### B1. Four-gate graded feasibility

Feasibility is a weighted mean of four ratios, each weight 0.25:

| Gate | Definition |
|---|---|
| placement | machines the decoder placed ÷ machines required |
| routing | flows routed ÷ flow demand as originally derived |
| power | generation ÷ demand, capped at 1 |
| sustain | `SIM_EQ_MAX_TICKS` ÷ critical path time, capped at 1 |

`terminal_rate = revenue × feasibility` is the GA's second objective. This must
be defined in Chapter 3 — it is the primary dependent variable in every results
table.

**Report the four sub-ratios alongside every feasibility figure.** Because the
weights are equal, a single gate at zero costs exactly 25 percentage points
regardless of the other three, and the headline number is close to unreadable
without the breakdown. Observed on one chromosome through two phases: Phase 2
placed *more* machines, pruned *fewer*, and routed a *higher* fraction, yet
scored 29 points lower, because two gates fell.

### B2. Discrete-event simulation as an independent check

A tick-level simulation (belts move one cell per tick, machines consume from
input buffers, run for `process_time`, emit to output buffers) is run on the top
layouts pre-disruption and post-recovery. It produces per-machine Gantt charts,
cumulative throughput, and a powered/brownout trace.

This is **direct evidence for RQ4** (validity and repeatability of the sandbox)
and should be presented as a validation instrument, not just a visualisation.
The static Gate 2 is a critical-path estimate that assumes every machine is fed;
the simulation does not. Where they disagree, the simulation is the stronger
claim.

### B3. Disruption scenario sampling

Crater positions are drawn uniformly over the grid and **rejected unless they
destroy at least one machine**, repeating until the required number of scenarios
is obtained. Justification: layouts occupy 6–12% of the grid, so only 12–24% of
uniform craters hit anything; a single fixed crater destroyed nothing in three
of five test layouts. Rejection sampling conditions the sample on a non-null
event while preserving unbiased geometry — dense clusters and large footprints
are struck more often, as an accident would — whereas centring on a uniformly
chosen machine would over-sample isolated ones.

The scenario set is seeded from the layout, so every recovery algorithm faces
identical craters. **This is essential to the GA-versus-SA comparison** and
should be stated as such.

### B4. Reproducibility

Relevant to RQ4. Layout decoding draws from an explicitly threaded RNG, and the
per-genotype seed uses `zlib.crc32` over a stable string rather than Python's
`hash()`, which is salted per process. Before this, the same chromosome produced
a different layout in every interpreter session. Runs are now reproducible from
`RANDOM_SEED` in single-process mode.

---

## PART C — Material available for Chapter 4

### C1. Layout generation results

From the SA full run (100 × 50):

| Layout | Machines | Feasibility | place / route / power / sustain | Belts |
|---|---|---|---|---|
| #1 | 55 | 98.7% | 0.98 / 0.97 / 1.00 / 1.00 | 59 |
| #3 | 80 | 93.8% | 0.84 / 0.91 / 1.00 / 1.00 | 72 |
| #5 | — | 93.1% | 0.96 / 0.98 / 1.00 / 0.78 | — |
| #7 | — | 91.4% | 0.93 / 1.00 / 1.00 / 0.73 | — |

### C2. Simulation corroboration — the strongest single result

```
Layout #1  PRE-BOMB : 55 machines, 59 belts, ran 41/55, starved at end 3
                      live_fraction 98%, sim revenue 10.000/tick
                      eq_tick 280, brownout 0/400
                      Gate2 static = True,  Gate2 simulated = True
```

A layout scored 98.7% feasible by the static model reached equilibrium in the
independent discrete-event simulation, ran 98% of its machines, and never
browned out. **This is the most defensible result in the study** and directly
answers RQ4.

### C3. Disruption and recovery

Regret across ten bombed layouts ranged 0.0396 → 8.2452. Layout #3's large
regret has a readable mechanism: the power gate collapsed from 1.00 to 0.00
post-disruption — the crater severed the thermal bank's fuel supply. That is a
concrete, interpretable fragility finding and is worth a paragraph of its own.

### C4. Computational performance

A 2.71× end-to-end speedup with bit-identical outputs, verified across eight
scenarios by hashing machine coordinates, routed path lengths, MHC, gate values
and recovery costs. Sources: connected-component pre-check to reject unroutable
A\* pairs in O(1); flat-array A\* interior replacing tuple-keyed dicts; indexed
flow matching. Reportable as a methods contribution.

---

## PART D — Threats to validity to declare in Chapter 4 or 5

Declaring these is stronger than omitting them; each is measurable.

1. **Single-crater sampling.** Every completed full run bombed each layout once,
   at a fixed coordinate. Regret figures in those runs are single samples and
   cannot distinguish a resilient layout from a lucky crater. Re-run with
   scenario sets before quoting regret.
2. **Population collapse.** The SA full run produced 20 Phase-2 candidates with
   12 distinct layouts and bombed 10 of which 6 were distinct; the GA run was
   worse (9 and 5). De-duplication is now implemented; earlier results
   over-count sample size.
3. **Search convergence.** 50 generations produced four distinct best-fitness
   values (SA) and 30 produced three (GA), with seven and four fruitless
   hypermutation triggers. Report convergence honestly; the encoding change in
   A4 addresses the cause.
4. **Rotation is not searched.** Every machine is placed at `R0` throughout.
   Since rotation determines which face carries the I/O ports, this is a fixed
   dimension of the layout problem and must be stated as a scope limitation.
5. **BOM and flow matrix are separate models.** The bill of materials is sized
   by throughput; the flow matrix pairs machines one-to-one. For `SC_bat` at
   rate 0.3 the BOM correctly builds six fitting units for three packaging units
   (1 ferri_part/tick demand against 0.5/tick supply), but the flow matrix wires
   one supplier per consumer and orphans three. A rate-aware matcher and a
   global logistics pool are implemented in the `_pool` notebooks; the `_fixed`
   lineage retains the original behaviour.
6. **Revenue counts intermediates twice.** `REVENUE_TABLE` prices intermediates,
   and revenue is credited at production regardless of destination, so a
   `steel_part` earns revenue and the `HC_bat` built from it earns revenue
   again. Over half an HC_bat factory's reported revenue is parts it consumes.
   This inverts the intended economics in which processing further is more
   profitable.
7. **Efficiency penalty is a magic constant.** A missing input multiplies a
   machine's efficiency by 0.01, compounding downstream, while the routing gate
   counts broken flows linearly. One broken flow can cost 43% of revenue while
   the routing ratio moves four points. The constant is not derived from
   anything and should be named and justified.
8. **Power gate is near-binary.** With a single thermal bank, `power_ratio` is
   1.00 or 0.00, so it swings the headline feasibility by 25 points on the
   success or failure of one belt.

---

## PART E — Recommended order of work

1. **Correct A1–A4 and A6–A7** in Chapters 1–3. Textual, and they are the
   discrepancies most easily checked against the code.
2. **Decide A5.** Objective 4 and RQ3 have no implementation. This needs either
   code or a re-scope before Chapter 4 can be written.
3. **Re-run both notebooks at full settings on the current code**, with scenario
   sets enabled. Earlier results predate the placement-attribution fix, the
   monotone-efficiency fix, de-duplication and scenario sampling, and are not
   comparable with each other or with anything produced now.
4. **Write Chapter 4** from Part C, with Part D declared.
5. **Formatting (Handbook §8.6.2–8.6.3):** tables numbered by chapter with the
   caption above; figures numbered by chapter with the caption below; each
   positioned after its first citation; both listed in the preliminary pages.
   The Gantt, throughput, layout-sequence and Pareto figures already produced
   will all need captions and numbering.

---

## One framing suggestion

The evidence supports a stronger claim about **method validation** than about
layout optimality. The search converges poorly and the layout generator has
known modelling gaps (D5–D8), but the disruption-and-recovery apparatus is
sound, reproducible, and independently corroborated by simulation (C2).

If Chapter 5 frames the contribution as *a validated, reproducible sandbox and
an explicit spatial framework for evaluating post-disruption reconfiguration* —
with layout quality as the input rather than the finding — the results in Part C
support it comfortably. Framing it as a layout-optimisation contribution would
require fixing the convergence and the modelling gaps first.
