# Review + refactor log — `flp_definitive_GA_ALNS_fixed.ipynb` & `flp_definitive_SA_ALNS_fixed.ipynb`

Reviewed and refactored 2026-08-09. Originals backed up to `_backup_prefix/*.bak`.

Both notebooks went from 50 → 54 cells. They remain identical except for
`zpf_recovery` (NSGA-II vs Simulated Annealing) and the ZPF budget config.

Verified by executing the full pipeline end-to-end on a reduced config
(POP=6, NGEN=1, MAX_MACHINES=40) — Phases 1 through 6 complete on both files.

---

## Part 1 — What changed

### 1. Regret dropped from the Phase 1 objective vector

Your reading was correct: regret is `pre_bomb_rate − post_recovery_rate`, so it
cannot exist before Phase 4 bombs something. Phase 1 builds layouts; Phase 4
stress-tests them. That two-stage design is unchanged.

What changed is only the bookkeeping. `OBJ_WEIGHTS` declared four objectives
while `evaluate_nsga2` returned `regret = 0.0` unconditionally — so NSGA-II was
handed a constant axis on which every individual ties. That is not neutral: it
inflates the non-dominated front and flattens crowding distance, diluting
selection pressure on the three objectives that *are* measured.

```python
OBJ_WEIGHTS: tuple = (-1.0, 1.0, -1.0)   # build_cost, terminal_rate, MHC
```

Regret is still computed and printed in Phase 4 exactly as before, and Phase 5
now also reports a **simulated** regret from measured throughput. Also fixed:
`run_nsga2`'s history dict and log line referenced `fitness.values[3]`, which
would have raised `IndexError` after the change.

### 2. The simulation is now connected — `SimEngine` actually runs

`SimEngine`, `BeltPath`, `plot_gantt` and `plot_throughput` were fully
implemented and completely unreachable. Two things blocked wiring them up:

- **`build_belt_paths(grid, flow_matrix)`** rebuilt belts by re-parsing
  `"{src}->{dst}"` grid labels, which collapses two materials running between
  the same machine pair and picks up superseded repair belts.
  → replaced by **`build_belt_paths_from_routed(routed)`**, one `BeltPath` per
  successfully routed flow, straight from the authoritative list.

- **`find_dag_roots`** returned "machines with no incoming flow that have a
  recipe". In the v4 pipeline `main_unit` supplies every raw material, so almost
  nothing qualified, the injection set came back empty, and **the simulation
  would have produced literally nothing**. It also injected *all* of a
  qualifying machine's inputs, which would have hidden exactly the starvation
  the Gantt exists to reveal.
  → replaced by **`build_injection_map(placed, routed)`**, which is per-material
  and only injects where a belt from `main_unit`/a depot actually lands.

New bridge, plus a new **Phase 5** cell:

```python
simulate_layout(result, label=...)  ->  (engine, eq_tick)
```

Phase 5 simulates the top `CFG.SIM_TOP_N` (default 3) layouts twice — pre-bomb
and post-Phase-4-recovery — and emits per layout:

- `v4_sim_gantt_layout_N.png` — paired Gantt, pre-bomb above, post-recovery below
- `v4_sim_throughput_layout_N.png` — paired cumulative production curves
- `v4_sim_regret_summary.png` — simulated revenue/tick, pre vs post

It also prints a table comparing the analytical estimate against measured
throughput and **flags every layout where the static Gate 2 and the simulation
disagree**. That comparison is the point: the static gate is a critical-path DP
that assumes every machine is fed; the simulation does not assume that.

Gate 2 inside the GA deliberately stays the cheap static `_chain_time` DP —
running a full simulation inside the fitness function would multiply an already
expensive evaluation. The simulation validates after the fact.

Sample output from the verification run (38 machines):

```
[SIM] Layout #1 PRE-BOMB:      ran=27/38 machines, starved at end=12, rev/tick=0.100
[SIM] Layout #1 POST-RECOVERY: ran=31/38 machines, starved at end=9,  rev/tick=0.200
end statuses: {'starved': 12, 'running': 23, 'idle': 3}
```

The Gantt reads clearly: `packaging_unit_0`, `ther_bank_0`, `planting_unit_0`
and `seed_picking_unit_0` are solid red for the whole run — permanently starved,
they never received a working input belt. The grinding and moulding units
alternate red/green, i.e. supply-limited batching. Post-recovery,
`fitting_unit_0` drops to idle grey where the bomb severed it.

`plot_gantt` was also rewritten to draw one bar per *contiguous status run*
rather than one bar per machine per tick (~20k patches for a 160-machine run),
and both plot functions now accept `ax`, `title` and `save_path` so they can be
composed into the paired figures.

### 3. Correctness fixes

| # | Fix | Effect |
|---|---|---|
| 1 | `place_machine` now stores `pm.instance_id` (was `machine_type.id`), so `remove_machine`'s comparison matches | Removed machines previously left permanent ghost footprints blocking A* forever. `remove_machine` now also erases the machine's belts and repaints surviving crossings. |
| 2 | `power` added to `NON_CONVEYED_MATERIALS`, excluded from `derive_flow_matrix` | Electricity no longer rides a fake conveyor. **MHC on the test layout fell from 46,753 to 497** — 97.8% of the old figure was one power belt. |
| 3 | Flow `intensity` is now the consumer's per-run quantity, not `min(sup_qty, con_qty)` | Every material flow used to come out at exactly 1.0, so MHC was plain belt length with no volume weighting at all. |
| 4 | `blf_decode(chromosome, grid, rng=None)`; threaded through `_decode_instances`, ALNS, Tabu, `evaluate_layout` | The decoder did `import random; random.shuffle(...)` inside its gene loop, ignoring every seeded rng and perturbing DEAP's own stream. Verified: same chromosome + `rng=Random(7)` now gives an identical layout across varying global seeds. |
| 5 | `repair_feasibility` no longer self-appends depots; callers extend explicitly | Each magic depot was added to `placed` twice, inflating `all_placed`, `build_cost` and power demand, and letting ALNS's `unplaced` count go negative. |
| 6 | `[GA]` recovery appends repair belts to **both** `flows` and `routed`; `feasible` counts only original machines | `unrouted` (objective 0 of the recovery search) could go **negative** and dominate everything — the search was rewarded for spawning depots instead of routing. |
| 7 | `[GA]` `zpf_recovery` now honours its `iterations` budget: `pop_size + pop_size*ngen` | The argument was assigned once and never referenced; the search always ran a hardcoded 20×30 regardless of `CFG.ZPF_ITERATIONS`. Now prints its actual budget. |
| 8 | `pwx` uses `range(len(a))` | The old bound silently excluded the final gene from crossover forever. |
| 9 | `ensure_full_connectivity` searches grid **edges** for `depot_unloader`, ranked nearest-first, and falls through on rejection | `depot_unloader` is `edge_only`, so the old ±8 local sweep produced only positions `place_machine` rejects — Strategy B could essentially never fire, which also made Phase 3's "5 passes" exit after one. |
| 10 | `SimEngine` consumes `common_extra` and uses `process_time` directly in ticks | Recipes needing a secondary ingredient (grinding r0 + `sandleaf_pow`) ran without it, and dividing by `TICK_SECONDS` put the sim on a different clock from `_chain_time`. |
| 11 | `blf_decode` caches the fallback sweep per footprint instead of rebuilding + reshuffling a ~4,700-element list per gene | 60-machine decode: 1.5s → 0.47s. |
| 12 | `ranked_pop` and `pareto_front` separated; Pareto scatter coloured by build cost | `selNSGA2(pop, k=len(pop))` returns the whole ranked population, not a front. The scatter read `ind._flp_cache`, set inside a joblib worker and therefore never present in the parent — it silently painted every point 0.0. |
| 13 | Phase 3 passes a seeded `polish_rng` to `connect_deep_polish` / `ensure_full_connectivity` | Both fell back to the global `random`. |

### 4. Legacy section

18 unreachable definitions moved to a marked **`APPENDIX — LEGACY`** section at
the end (614 lines), with a table mapping each to its replacement. Active code
is 4,104 lines. Verified: **no active cell references any legacy symbol**, and
no unreferenced definitions remain in the active half.

Moved: `FitnessResult`, `calculate_metrics`, `evaluate_fitness`,
`cull_unlinked_machines`, `evaluate_with_simulation`, `evaluate_search_fitness`,
`greedy_rotation_search`, `ProductSpec`/`ALL_PRODUCTS`, `print_grid`, old
`build_belt_paths`/`find_dag_roots`. `_to_fitness_result` was deleted outright.

`plot_layout`'s `result: FitnessResult` annotation was relaxed — annotations
evaluate eagerly outside IPython, so it would have broken as a plain script.

---

## Part 1b — Power economy and equilibrium (second pass)

### `STARTUP_FREE` was dead, and power was never charged at all

`STARTUP_FREE = True  # during startup, power is not charged` appeared exactly
once in the notebook — its own definition. `'power'` never appeared inside
`SimEngine.tick()`. Power was free during startup, free at equilibrium, and free
forever; the only check was one static comparison on the layout.

It now controls a **fixed-tick grace window** (`CFG.POWER_GRACE_TICKS = 150`),
after which every placed machine draws `power_cost` per tick from a pool fed by
the thermal banks.

**Why a fixed window and not "until equilibrium".** Gating a cost on equilibrium
is exploitable in the worst direction. A layout that never stabilises would
never start paying — and starving machines is precisely how a layout avoids
stabilising. "Free until equilibrium" rewards broken factories with permanent
free power. A fixed tick count cannot be manipulated by the layout being
evaluated. Demand is likewise summed over every *placed* machine, running or
not; charging only running machines would reward starving them.

### Equilibrium was measured in log entries, not ticks

```python
r1 = rate(self.production_log[-window:])   # last 30 ENTRIES, not 30 ticks
```

Measured on a real run: the last 30 entries spanned **8 ticks**. The comparison
window narrowed as throughput rose, so a factory that sped up looked *more*
stable. `throughput_at_equilibrium` then divided that entry sum by 30 as though
it were ticks — which is why simulated revenue came out as implausibly round
numbers (0.100, 0.200, 0.300, 0.900). Both now select by tick via `_rate_over`.
Real figures from the same layout afterwards:

```
throughput/tick: {'ferri_part': 1.0, 'ori_pow': 1.5, 'ferrium': 1.0, 'SC_bat': 0.033}
revenue/tick = 2.0000
```

### Equilibrium ignored starved machines — confirmed exploitable

`is_equilibrium` consulted only `production_log`, and a machine that never
completes a recipe writes nothing to it. It was structurally invisible, so a
layout could leave most of its machines permanently starved and still be
declared converged. It was *stably broken*.

New `live_fraction(window)` requires a share of recipe-bearing machines to have
actually produced. `CFG.SIM_MIN_LIVE_FRACTION = 0.5`. Demonstrated on a real
layout:

```
live_fraction = 47%  (need 50%)
is_equilibrium = False   |   ignoring liveness = True   <- old behaviour
```

That layout would have been reported as converged under the old rule.

### Gate 1 could never fail — corrected, then corrected again

**First attempt (wrong, since reverted).** I read
`Recipe([("HC_bat",1)], [("power",1100)], 100)` as an energy batch — 1100 units
per 100-tick run, i.e. 11/tick — because that is what an output quantity means
for every *other* recipe, and divided generation by `process_time`.

That was a misreading. Power is not an item; it never rides a belt. The config
says what it actually is:

```python
BATTERY_CAPACITY: int = 1100   # power supplied per Thermal Bank
```

A **rating**: the bank supplies 1100 while burning, and one HC_bat sustains that
for 100 ticks. `power_cost` is likewise a rated draw, so the original
`output > demand` compared like with like and was correct.

The damage from getting this wrong was measurable — one correctly-sized
generator became seventeen, which could not be fuelled through `main_unit`'s six
output ports:

```
POWER_RATE_CORRECT=True :  BOM=34  ther_banks=17   fuel flows routed  1/17   overall 15/43
POWER_RATE_CORRECT=False:  BOM=18  ther_banks= 1   fuel flows routed  1/1    overall 14/27
```

Now defaults to `False`; the flag is kept only for comparison.

**The real missing constraint** was never sizing — it was that a bank supplies
power whether or not anything feeds it. `_power_output(placed, routed)` now
credits a bank only if a successfully routed flow delivers one of its recipe
inputs. `find_unconnected_ther_banks()` could always identify these; no gate
ever consulted it. Verified:

```
rate=0.15: banks=1  fuelled=1 | demand=160 output=1100 power_ok=True
rate=0.30: banks=1  fuelled=0 | demand=180 output=   0 power_ok=False
```

Gate 1 now fails for a real reason — an unfuelled generator — without inflating
the machine count. `SimEngine` credits `rating × process_time` per burn so the
simulation's energy balance matches the static gate.

### The raw-import bottleneck: `main_unit`'s six output cells

Separate from power, and probably the dominant limit on routing completeness.

`main_unit` is 9×9 but exposes only **6 output belt cells** (3 on the top face,
3 on the bottom, at `dx ∈ {1,4,7}`), and it is the *only* `io_source` the BOM
ever builds — `derive_rate_balanced_bom` never added a `depot_unloader`, even
though `derive_flow_matrix` already treats them as sources and round-robins
imports across all of them.

So every raw material for the entire factory funnels through six cells:

```
rate=0.05:  6 flows leaving main_unit,  4 routed | overall 10/14
rate=0.15: 11 flows leaving main_unit,  5 routed | overall 14/27
rate=0.30: 16 flows leaving main_unit,  2 routed | overall 15/40
depots_in_BOM = 0 at every size
```

The `FLPConfig` comment attributes poor routing at scale to general grid
congestion. The evidence points at this one building's port geometry instead.

### The unrouted flows are almost entirely at the boundary, not in the chain

Breaking a 34-machine layout's routing down by flow type settles what the
problem actually is:

```
machine-to-machine flows :  16 routed 15   (94%)
flows OUT of main_unit   :  21 routed  0   (raw imports)
flows INTO main_unit     :  16 routed  4   (finished goods)
```

**The production chain itself routes at ~94%.** Nearly every failure is material
entering or leaving the factory through one 9×9 building.

`derive_flow_matrix` has always recognised the full set of terminators —
`io_sources = (main_unit, depot_unloader)` and
`io_sinks = (main_unit, depot_loader, stash)` — but the BOM built **exactly one
`main_unit` and zero of everything else**, at every layout size. The mechanism
existed; nothing ever instantiated it.

Three new knobs (all default **0**, i.e. unchanged behaviour). A value ≥ 1 is an
absolute count; a value in (0,1) is a fraction of BOM size:

```python
IMPORT_DEPOTS:  float = 0.0   # depot_unloader, edge-only raw-material sources
EXPORT_STASHES: float = 0.0   # stash, 3x3 placeable anywhere, product sinks
EXPORT_LOADERS: float = 0.0   # depot_loader, edge-only product sinks
```

Measured on a 34-machine BOM (rate 0.40):

```
 depots stashes | overall | imports | exports | chain
      0       0 |  19/53  |    0/21 |    4/16 | 15/16
      6       0 |  26/53  |    9/21 |    3/16 | 14/16
      0       6 |  30/53  |    3/21 |   11/16 | 16/16
      6       6 |  40/53  |   11/21 |   13/16 | 16/16
```

End-to-end through `evaluate_layout` with the fraction form:

```
       setting  BOM  placed  pruned    routed   pct
     off (0,0)   34      24      10     18/34   53%
   0.15 / 0.15   44      37       7     31/37   84%
```

`stash` is the more effective sink — it is 3×3 and placeable anywhere, so it can
sit beside the machine that needs it, whereas `depot_loader` is edge-only and
ends up far away. Adding loaders on top of stashes gave no further gain.

**Caveat: the scoring hides the win.** With terminators, routing goes 61% → 95%
and pruning 10 → 4, but `terminal_rate` *falls* (6.510 → 5.709), because `stash`
costs 10 power each and the thermal bank's own fuel belt now competes for the
congested ports — the power gate flips to `False`. Since `_feasibility_ratio` is
a flat mean of four gates, a +0.34 routing gain (worth +0.085) is swamped by a
zeroed power gate (worth −0.25). Same dilution problem described under "the
objective rewards going bigger". Fixing the aggregation is the prerequisite for
the GA to *see* this improvement.

### Two bugs this pass introduced and then fixed

Worth recording, because both are easy to reintroduce:

1. **Brownout deadlock.** Gating *all* machines on power meant a brownout
   stopped the thermal banks from burning fuel, which is the only way the pool
   refills — all 19 machines sat `unpowered` from tick 61 to 400. Machines with
   `is_power_src` are now exempt.
2. **Battery starvation.** Batteries had no `supply_rates` entry, so injection
   fell back to `qty/process_time` = 0.01/tick: a bank waited 100 ticks for one
   battery, then burned it over another 100. Measured 99 ticks starved before
   its first run — this is why `ther_bank_0` was a solid red bar in the earlier
   Gantt. Batteries now import at 0.05/tick against a 0.01/tick burn.

After both fixes: `brownout ticks = 0/600`, thermal bank first runs at tick 19,
49,500 power generated, 16 of 18 machines running at the end.

A new `unpowered` status (purple) appears in the Gantt.

---

## Part 1c — ZPF recovery semantics (third pass)

The intended model, confirmed with the author:

- **Free circle (≤ r1)** — reconfigure freely, no penalty.
- **Penalty ring (r1 < d ≤ r2)** — usable, but costed, scaled by distance from
  the blast. A small disruption must not justify rearranging the whole factory.
- **Beyond r2** — frozen. Machines must not move.
- **Belts** — free to be re-routed anywhere.
- Membership is by **majority of a machine's cells**, not a strict fit: a 3×3
  belongs to a circle when at least 5 of its 9 cells are inside.

The penalty term (`5.0 × distance(final position)` for machines in the ring) is
therefore **correct as written** — an earlier draft of this document claimed the
direction was inverted; that was a misreading of the model.

### Zone membership was decided by one cell

`machine_zone` returned `self.zone(pm.x + pm.w // 2, pm.y + pm.h // 2)` — the
zone of the single centre cell. A machine straddling a boundary was classified
on one arbitrary square, and a large machine could be called "stable" (frozen)
while most of its footprint sat inside the blast circle.

Now a majority-of-cells test. Verified against a 3×3 with the crater at (22,22),
r1=5, r2=12:

```
3x3 at (28,22): 6/9 cells in r1  -> flexible
3x3 at (33,22): 0/9 in r1, 9/9 in r2 -> penalty
3x3 at (36,22): 3/9 in r2        -> stable
```

### Recovery relocated machines the blast never touched

`_place_order` scanned the disruption box from its top-left corner and took the
**first** fit. It never tried a machine's original position — so an undamaged
machine in the ring was hauled toward the corner for no reason, maximising
disruption by default and then scoring it as an improvement.

Recovery now attempts each machine's **exact original position first**, and only
machines actually caught in the crater (`machine_zone == "unusable"`) are forced
to search. Verified with the crater on the factory centroid, GA variant:

```
movable=16   recovered=17/17   unplaced_ids=[]
main_unit_0      zone=unusable  (6,24)  -> (5,11)   moved 13.0 cells
packaging_unit_0 zone=penalty   (1,19)  -> (15,15)  moved 14.6 cells
refining_unit_1  zone=penalty   (12,16) -> (0,19)   moved 12.4 cells
...13 others                                        STAYED PUT
STABLE machines that moved: none
```

Only the destroyed `main_unit` moved, plus the two machines its new 9×9
footprint displaced. SA variant: 15 of 16 stayed put.

### Other recovery fixes

- **Candidate acceptance** now uses the same majority rule
  (`machine_zone(candidate) != "stable"`) instead of a centre-point
  `hypot(...) <= r2` test, so the placement geometry and the zone classifier
  finally agree. This also removes the GA/SA geometry mismatch noted earlier —
  both variants now use identical acceptance logic.
- **`MIN_MACHINE_SPACING` is honoured.** `_place_order` called only
  `place_machine`, skipping the 1-cell clearance every original layout is built
  with, so recovery packed flush. It now tries `clearance=1` first and falls
  back to `0` only if the circle is genuinely too tight. Verified: min
  inter-machine gap is 1 both pre-bomb and post-recovery.
- **Lost machines are now reported.** Unplaceable machines were dropped
  silently, visible only through the `feasible` boolean. Recovery results now
  carry `unplaced_ids`.
- Because undamaged machines return to their original spot, an `edge_only`
  depot inside the circle is no longer lost — it simply stays where it was.
  A *destroyed* `edge_only` machine still cannot return, since no grid edge
  exists inside the r2 box. That remains a known limitation.

### Disturbing a healthy machine was free — now priced

**Destruction** is `any(cell in crater)`. A single overlapping cell writes the
machine off; a 3×3 crater clipping the corner of a 9×9 `main_unit` destroys it
entirely. This is an explicit modelling assumption — blast size is tuned via
`ZPF_W`/`ZPF_H`, not via an overlap threshold. A partial-damage rule would not
work anyway: a "surviving" machine would still overlap the `BLOCKED` crater and
so could never be re-placed where it stands.

Everything else is **healthy**, and because recovery now tries the original
position first, a healthy machine that ends up somewhere else was moved *by the
search's choice*. That was free, and worse than free: the only cost of a move
was the incidental change in the zone-occupancy term (`5 × distance`), which
*shrinks* toward the blast — so hauling an untouched machine inward, or into the
free circle where it is zero, actively **improved** the objective. Same class of
loophole as the pre-r2-cutoff behaviour, pointing the other way.

Now charged, using the previously-unread `CFG.PENALTY_PER_MOVED_MACHINE`:

```
cost = PENALTY_PER_MOVED_MACHINE × (1 + d_original / r2)
```

per machine whose position changed, **excluding** machines that were in the
crater (they had no choice). Scaled by the machine's *original* distance from
the blast, so disturbing something at the ring's edge costs about twice what
disturbing something beside the crater does — it prices **reach**, not distance
travelled. Deliberately independent of how far the machine was dragged: a small
disruption must not justify rearranging the far side of the factory.

Verified on the real recovery (crater on the factory centroid):

```
GA:  destroyed=[main_unit_0]  avoidable moves=[packaging_unit_0, refining_unit_1]
     machines_disturbed=2   relocation_penalty=337.0   zone_penalty=542.7   mhc=990
SA:  destroyed=[main_unit_0]  avoidable moves=[]
     machines_disturbed=0   relocation_penalty=  0.0   zone_penalty=526.5   mhc=726
```

For reference, the alternatives on the same two moves were: flat-per-machine
200.0, and displacement-scaled 224.4.

Recovery results now carry `zone_penalty`, `relocation_penalty`,
`machines_disturbed` and `unplaced_ids`, and Phase 4 prints them per layout.

**A note on search space.** A 3×3 crater typically destroys one machine, so if
healthy neighbours were hard-pinned the recovery search would be ordering a
single item and GA vs SA could never differentiate. The freedom to shuffle
neighbours is what makes the layered circle a reconfiguration mechanism and what
gives the search something to optimise — this penalty prices that freedom rather
than removing it.

### `_chromosome_repair_seed` was not reproducible across runs

It used `hash()` on a tuple containing `machine_id` strings, and Python salts
string hashing per process. The docstring claims it "makes repair a
deterministic function of the genes" — it was deterministic within a single
interpreter only. Three consecutive processes, same chromosome:

```
seed=3419549971  layout_md5=bad9df18403f
seed=3674244194  layout_md5=f3eb6df91362
seed= 340575188  layout_md5=c4d7b9fdd32e
```

Now `zlib.crc32` over a stable string. Verified identical across
`PYTHONHASHSEED=0` and `=1`. (`individual_repair_seed` hashes floats, which are
not salted, so it was already fine.)

---

## Part 1d — Why a good candidate can vanish before the final figures

A layout printed in Phase 2 can fail to appear at the end for **four** distinct
reasons, none of which produced any output:

**1. Only `PHASE4_TOP_N` of `PHASE2_CANDIDATES` survive.** Defaults are 20 in
and 10 out, so **half the polished candidates are never bombed and never
plotted**, with no message. This is the most likely cause on a full run.

**2. Feasibility does not dominate the ranking.** The sort key is

```python
score = feasibility × WEIGHT_FEASIBILITY + terminal_rate × WEIGHT_REVENUE
      = feasibility × 100.0            + terminal_rate × 0.2
```

A 3.4-point feasibility lead (3.4 score) is erased by a terminal-rate lead of
17. Since `terminal_rate = revenue × feasibility` and revenue is unbounded, this
gets easier as revenue grows. Worked example from the new report:

```
Rank  Feasibility  TerminalRate   Score   Bombed?
   1        91.5%        2.4699   91.99   yes
   2        87.9%       17.8300   91.47   yes
   3        84.0%        5.0300   85.01   NO  <- cut
   4        70.0%       40.0000   78.00   NO  <- cut
```

Rank 2 nearly beats rank 1 on revenue alone despite being 3.6 points less
feasible.

**3. The filename comes from the boolean gate, not the percentage.** A
91.5%-feasible layout is still `PARTIAL` — `_feasibility_ratio` is the graded
score, `result["feasible"]` is the hard 4-gate boolean. So its figure is written
as `v4_layout_best_partial_N_sequence.png`, never `v4_layout_top_N_*`. The
layout may be on disk under a name you weren't looking for.

**4. Phase 6 swallows plotting failures.** `plot_zpf_sequence` is wrapped in
`try/except Exception` that prints a traceback and continues, so a layout whose
figure fails to render is simply absent from the outputs.

Also note Phase 5 simulates only `SIM_TOP_N` (default 3) of the 10 bombed
layouts, so Gantt charts exist for fewer layouts still.

### Added: a ranking report at the Phase 3 → Phase 4 boundary

Phase 3 now prints the full ranking with scores, marks the cut line, and warns
explicitly when a cut layout has higher feasibility than one that was kept:

```
  [!] 1 cut layout(s) have HIGHER feasibility than the weakest one kept (87.9%):
      rank 3: 84.0% -- outranked on revenue, not feasibility.
      Raise CFG.PHASE4_TOP_N, or lower CFG.WEIGHT_REVENUE, to keep them.
  2 of 4 candidate(s) are NOT bombed and NOT plotted.
```

If you want feasibility to strictly dominate, set `WEIGHT_REVENUE` low enough
that `WEIGHT_REVENUE × max_rate < WEIGHT_FEASIBILITY × min_feasibility_gap`
you care about — or raise `PHASE4_TOP_N` to `PHASE2_CANDIDATES` so nothing is
discarded before bombing.

---

## Part 1e — Control Panel (§1.5)

Every tunable parameter now lives in **one cell, immediately after the imports**
(cell 4, "Control Panel"). Previously they were split across two places: the
geometry and time constants sat in the imports cell near the top, while
`FLPConfig` sat ~30 cells down, next to the DEAP setup.

Pure code motion — the `FLPConfig` body, the `RIGOUR` profile and the geometry
constants were moved verbatim, so **no value changed**. Verified: 8 scenarios
(both notebooks × two BOM sizes × layout and recovery), comparing coordinate and
routed-path MD5s plus MHC, path counts, chain time, revenue, power gate, recovery
cost and relocation penalty — **0 mismatches**.

What the cell now contains, grouped by the phase each group drives:

| Group | Drives |
|---|---|
| `RIGOUR` | whole run — `"quick"` (~5-10 min) vs `"full"` |
| Geometry & time | `FactoryGrid`, `blf_decode`, belt travel |
| Product mix & BOM | `derive_rate_balanced_bom` — layout size and complexity |
| GA / NSGA-II | `run_nsga2` (Phase 1) |
| Layout repair | `evaluate_layout` — ALNS, Tabu, cleanup (Phases 2-3) |
| Feasibility gates | `_feasibility_ratio`, `evaluate_layout` |
| ZPF disruption | `zpf_recovery` (Phase 4) |
| Simulation & power | `simulate_layout` (Phase 5) |
| Phase widths | how many candidates reach Phases 2, 4, 5, 6 |

It prints a summary on run, so every parameter in force is visible in the output:

```
Grid          : 70x70   spacing=1
Search        : POP=10 NGEN=2 MAX_MACHINES=40 rate band=0.02-0.06 activation=0.4
Repair        : ALNS=2 TABU=2 prune=True full_routing=True
Phase widths  : phase2=3 phase4=2 sim=2
ZPF           : crater 3x3 @(22,22) r1=5.0 r2=12.0 budget=18
Power         : enforce=True grace=150 rate_correct=False import_depots=0
```

The accompanying markdown carries the calibration measurements — the BOM step
function and its flat floor below 0.15, the fact that `MIN_TERMINAL_RATE` only
affects generation 0, the over-cap fractions, and that complexity is bounded by
routing rather than grid space — so the numbers are next to the knobs they
explain.

Deliberately **not** moved (model data, not tuning): `MACHINE_CATALOGUE` and
`REVENUE_TABLE`, `BATTERY_POWER`, `NON_CONVEYED_MATERIALS`, and
`TARGET_PRODUCTS`/`ALL_RECIPES` (both derived from the catalogue).

### Two things the audit caught

**Simulated-annealing knobs in the GA notebook.** `SA_INITIAL_TEMP`,
`SA_COOLING_RATE` and `SA_WEIGHTS_INIT` sat in the GA notebook's config and were
**never read by anything** — not in code, not even in a comment. They are
left over from the SA sibling; the GA notebook's ZPF recovery is NSGA-II,
budgeted by `ZPF_ITERATIONS` / `ZPF_POP_SIZE`. Removed, with a note in their
place. (The SA notebook has no equivalent GA-only leftovers: `ZPF_POP_SIZE` is
correctly absent there.)

**A regression the move itself introduced.** The `blf_decode` cell declared
`BLF_VERBOSE = False` at module level. That was harmless while the config cell
ran *after* it, but the panel now runs *first*, so the re-declaration silently
reset the knob and `SHOW_BLF_WARNINGS` had no effect. Changed to
`BLF_VERBOSE = globals().get('BLF_VERBOSE', False)`, which keeps the cell
runnable standalone without overwriting the panel. Verified:

```
CFG.SHOW_BLF_WARNINGS=False -> BLF_VERBOSE = False   OK
CFG.SHOW_BLF_WARNINGS=True  -> BLF_VERBOSE = True    OK   (was False before the fix)
```

Post-audit both notebooks report **zero unused config fields** and no
panel-owned name is clobbered by a later cell.

---

## Part 1f — Rip-up and reroute

Belts were **write-only**: `place_belt()` added them and nothing ever removed
one. So the first flow to claim a corridor kept it forever, and a later flow
with no alternative simply failed — even when a small rearrangement would have
satisfied both. This is the classic detailed-routing problem, and the classic
answer is rip-up-and-reroute.

`ripup_and_reroute()` takes each unrouted flow, evicts up to `RIPUP_MAX_EVICT`
belts crossing the bounding box between its two machines, routes the blocked
flow into the freed space, then re-lays the evicted ones. The move is kept
**only if the total routed count strictly increases**, so the pass is monotone —
it can never make routing worse. `FactoryGrid.rebuild_belts()` was added to make
the belt layer rewritable.

Measured (SA notebook, terminators at 0.15):

```
 rate  BOM    before   RIPUP=2  gain  chain unrouted
 0.15   24     21/27     23/27    +2               0
 0.25   34     30/40     32/40    +2               0
  0.4   44     38/53     41/53    +3               0
```

The important column is the last one: after rip-up, **zero machine-to-machine
flows remain unrouted** in every case. Everything still unconnected is a
factory-boundary flow. A production-line-ordered retry pass — routing each
chain's flows together, or prioritising by revenue line — would therefore have
no headroom left in the chain; the boundary is where the remaining work is, and
that is what `IMPORT_DEPOTS` / `EXPORT_STASHES` address.

`RIPUP_ROUNDS` defaults to **0** (off). Set it to 2–3 to enable.

### Revenue double-count (confirmed)

Intermediates are genuinely sellable, but processing further is meant to be more
profitable. That makes the current arithmetic wrong rather than merely coarse:
`_calculate_revenue` credits every machine's output at production, so a
`steel_part` earns revenue **and** the `HC_bat` built from it earns revenue
again. You cannot sell the part and also sell the battery containing it.

Measured contribution to gross revenue:

```
target=buck_cap_A  gross 14.00 |  buck_cap_A 100%
target=SC_bat      gross  8.00 |  SC_bat  75%  +  ferri_part  25%
target=HC_bat      gross 11.40 |  HC_bat  47%  +  steel_part  53%
```

Over half of an HC_bat factory's revenue is parts it consumes. The filling
chains get no equivalent bonus (ground powders and steel bottles are unpriced),
which is why they rank *last* by terminal-rate-per-machine despite carrying the
highest unit revenue — **the double-count inverts the intended economics of
"process further to earn more"**.

The principled fix: credit revenue only for output that actually reaches an
`io_sink`. `derive_flow_matrix` Stage 3 already identifies exactly those flows.
That also removes the second artefact — a battery manufactured and then burned
by a thermal bank currently earns full revenue *and* supplies power.

**Not yet implemented** — it changes the objective, so it needs a decision.

---

## Part 1g — Reading the feasibility percentage

A real run showed feasibility going **80% → 50% → 79%** across Phase 1, Phase 2
and post-bombing, which looks like the layout degrading then recovering. It is
neither. Reproduced on the same chromosome:

```
 rate  phase  placed  removed  flows  routed |  place route power  sust |  FEAS
 0.15     P1      16        2     23      14 |   0.89  0.61  1.00  0.76 |   81%
 0.15     P2      18        0     27      23 |   1.00  0.85  0.00  0.22 |   52%
```

**Phase 2 is strictly better** — more machines placed, none pruned, higher
routed fraction — and scores 29 points lower. `_feasibility_ratio` averages four
ratios at equal weight, so any one gate hitting 0 costs exactly **25 points**
regardless of the other three. Here `power` went 1.00 → 0.00 and `sustain`
0.76 → 0.22 (Phase 2 keeps more machines, so `_chain_time` lengthens).

The post-bomb rise is the same coin: `zpf_recovery` re-derives the flow matrix
from scratch, so a *different* greedy matching gives the thermal bank a routable
fuel belt, `power` flips back to 1.00, +25 points. Measured flow counts go
23 → 25 across the bombing, confirming the graph is rebuilt rather than damaged.

With one thermal bank, `power_ratio` is effectively **binary**.

Consequence to watch: `regret = max(0, pre − post)` floors at **0.0000**
whenever the bomb "improves" the score — which is what both layouts in that run
reported. That is the comparison being invalid, not resilience being shown.

### Implemented: gate breakdown everywhere feasibility is printed

`_feasibility_breakdown()` returns the four sub-ratios; `_feasibility_ratio()`
now calls it, so the two cannot drift. Reported in Phase 2 per candidate, as a
column in the Phase 3 ranking table, and on both Phase 4 bomb lines — where a
swing over 20 points also prints an explicit warning that one gate flipping
explains a jump that size and that the two graphs aren't comparable.
Reporting-only: 0 behaviour mismatches.

### On replacing the battery system with a flat rating

Measured, so the trade is explicit.

**It buys nothing for routing.** Battery fuel is 1 flow out of 27–53 — **2–4% of
the graph**:

```
rate=0.15: BOM= 18 banks=1 flows= 27 fuel flows= 1 ( 4% of graph)
rate=0.40: BOM= 34 banks=1 flows= 53 fuel flows= 1 ( 2% of graph)
```

**It buys exactly 25 points of score stability**, because it removes the binary
gate. Note the semantics are already what you intend — a burned battery supplies
its rating for `process_time` ticks — so no model change is needed for that.

**There is a cheaper option that needs no code change at all:** set
`CFG.W_POWER = 0.0`. The weighted mean already renormalises over whatever
weights are non-zero, so power drops out of the score while the physics, the
`power_ok` boolean and the Phase 5 brownout tracking all stay intact.

```
 rate  phase | W_POWER=0.25 (now) | W_POWER=0.0
 0.15     P1 |               81% |         75%
 0.15     P2 |               52% |         69%
 0.25     P1 |               57% |         75%
 0.25     P2 |               48% |         64%
```

The 25-point cliffs disappear and the residual P1→P2 drop is `sustain` alone —
which is a real effect (more machines ⇒ longer critical path), not an artefact.

---

## Part 1h — Defaults turned on, and what they did

`IMPORT_DEPOTS = 0.15`, `EXPORT_STASHES = 0.15`, `RIPUP_ROUNDS = 2` are now the
defaults in both notebooks, in both the `quick` and `full` profiles. Set them to
`0.0` / `0` to reproduce the previous behaviour.

Diagnosis from a real quick run (seed 60) before the change — routing was never
the problem:

```
                            config  placed   routed   FEAS  gates
      as you ran it (all defaults)      28    38/49   46%  place 0.90 route 0.78 power 0.00 sust 0.14
           + terminators 0.15/0.15      33    36/41   67%  place 0.80 route 0.88 power 0.00 sust 1.00
             + terminators + ripup      33    37/41   68%  place 0.80 route 0.90 power 0.00 sust 1.00
```

The dead gates were `power` (0.00) and `sustain` (0.14 — `chain_time` roughly
seven times the tick budget). **The terminators' biggest effect is on `sustain`,
not routing**: giving the chain real endpoints collapses the critical path that
`_chain_time` measures.

### Full quick run with the defaults on

```
  Candidate  1: Rate=3.9494, Cost=280, MHC=2684, Feasibility=98.1% [PARTIAL]
                 gates: place 0.97 route 0.95 power 1.00 sust 1.00  (placed 33/34, routed 40/42)
  [RIPUP] recovered 1 connection(s)

  Layout #1
    Pre-Bomb  : Rate=3.7332, Feasibility=92.7%   [place 0.97 route 0.98 power 1.00 sust 0.76]
    Post-Bomb : Rate=0.4716, Feasibility=94.3%   [place 0.97 route 0.80 power 1.00 sust 1.00]
    Regret    : 3.2616
  [SIM] Layout #1 PRE-BOMB: ran=24/33, starved at end=3, sim revenue/tick=2.000
```

Compared with the same notebook before the change:

| | before | after |
|---|---|---|
| best Phase 2 feasibility | 52.2% | **98.1%** |
| power gate | 0.00 | **1.00** |
| sustain gate | 0.22 | **1.00** |
| simulated revenue/tick | 0.000 | **2.000** |
| regret | 0.0000 | **3.2616** |

Two of those matter beyond the headline:

- **The thermal bank is now fuelled.** The extra `depot_unloader`s give it a
  routable fuel belt, so `power` reaches 1.00 honestly rather than by being
  dropped from the score. `W_POWER` stays at 0.25 — it was not needed.
- **Regret is finally measuring something.** It was pinned at 0.0000 because the
  bomb kept "improving" the score; it now records real damage (rate 3.73 → 0.47).
  The pre/post flow-matrix comparability caveat still stands, but the metric is
  no longer trivially zero.

Small layouts (BOM ≈ 14) still show `power 0.00`: with one thermal bank the gate
is binary, and at that size the fuel belt does not always land. That is the
remaining honest failure mode, and the gate breakdown now names it.

---

## Part 2 — Still open (deliberately not changed)

These are modelling decisions, not bugs. They affect what your results *mean*,
so they belong in the write-up if you don't change them.

### The BOM and the flow graph still disagree — **[verified]**

For `SC_bat @ rate 0.3`, `derive_rate_balanced_bom` sizes 6 refining + 6 fitting
+ 9 shredding + 3 packaging. `derive_flow_matrix` wires **one** fitting and
**one** shredding per packaging unit — Stage 1 keys `matched_demands` on
`(material, consumer_id)` and breaks after the first match. The surplus is
classified "unconsumed final product" and dumped into `main_unit`:

```
fitting_unit_3   -> main_unit_0  ferri_part
shredding_unit_3..8 -> main_unit_0  ori_pow
```

The throughput reasoning that justifies the machine counts has no representation
in the topology being scored. In the live run, **10 of 26 machines (38%) were
pruned as unconnectable.** This is the single biggest remaining gap; fixing it
means making Stage 1 match on *rate* (splitting a consumer's demand across
several suppliers) rather than one flow per ingredient.

### `all_placed` is asserted about machines that were then removed

`evaluate_layout` computes `all_placed` before `connect_or_remove_unlinked`, so
it reports `all_placed=True, len(placed)=16, genes=26, machines_removed=10`. The
behaviour is documented and intentional, but the honest reading is "every gene
was placeable in isolation", not "every machine was built". Phase 3 carries the
flag forward unchanged.

### The BOM still does not manufacture its own battery fuel

Fixed in Part 1b: the gate units, the bank count, and the simulation charging.
**Not** fixed: `derive_rate_balanced_bom` appends thermal banks *after* the
expansion loop has finished, so their battery demand never re-enters the queue.
It also hardcodes recipe index 2 (`HC_bat`) regardless of what the factory
makes — an SC_bat factory produces `SC_bat` while its banks demand `HC_bat`:

```
BOM for SC_bat@0.3:   {packaging_unit: 3, ..., ther_bank: N}
ther_bank needs      : HC_bat
BOM actually produces: ['SC_bat']
```

So batteries are always imported from `main_unit`/depot rather than produced
on site. That is a legitimate model if buying fuel is allowed — the simulation
now prices it as an import with a real arrival rate — but the power loop is not
closed, and the thesis should say so. `ProductSpec.power_battery` (in the
legacy appendix) had the correct per-product mapping if you want to close it.

### Merged from the `_radial` branch

`flp_definitive_*_radial.ipynb` are forks of this work with a different recovery
placement strategy. Two ideas from them were worth taking, and one was not.

**Taken — hub placed first.** `order = sorted(order, key=lambda pm: not
pm.machine_type.singleton)` puts `main_unit` at the front of the placement
queue. Losing it costs every raw import and every product sink at once, and as
the largest machine (9×9) it is the most likely to fail to fit if placed last.
This is also the **only** thing in the notebook that reads `singleton`.

**Taken — spiral outward from the machine's original position.** Recovery
previously scanned the disruption box from its top-left corner, so a displaced
machine could be thrown to the corner even when a neighbouring cell was free.
Searching radially from where it used to be minimises displacement, which is
what the relocation penalty is trying to price anyway.

**Taken — port-in-bounds check.** `blf_decode` verifies that a machine's belt
connect points lie on the grid; recovery did not.

**Not taken — unbounded expansion.** `_radial` sets
`max_search_r = max(grid.width, grid.height)` and expands until it finds a slot,
which lets a movable machine land anywhere, including deep in frozen territory.
That reopens the "placing outside the circle" loophole the r2 cutoff closed. The
merged version keeps the spiral but rejects any candidate whose majority falls
outside r2, and caps the radius at `2 × r2 + machine size`.

Verified with a crater placed directly on the `main_unit`:

```
crater on the main_unit at (4,41):
   destroyed=1 ['main_unit_0']   movable=8
   main_unit survived: True   unplaced=0   machines moved=6
   displacement: mean=8.6  max=11.3
   relocated into frozen zone: none
```

The hub is destroyed and successfully re-placed, its 9×9 footprint displaces
five neighbours, and containment holds.

### The `place` gate was measuring routing, not placement

The pipeline does place everything first and route second — `blf_decode` →
`derive_flow_matrix` → `route_belts`. So the placement gate should read 1.00
whenever the decoder succeeded. It didn't:

```
 rate  genes  after BLF  blf failed  pruned later  final  place gate  route gate
 0.05     14         14           0             0     14        1.00        1.00
 0.15     24         24           0             1     23        0.96        1.00
 0.30     34         34           0             4     30        0.88        0.90

rate=0.15: all_placed=True  but placement gate=0.96
```

**BLF placed 100% of machines in every case.** The gate fell only because
`connect_or_remove_unlinked` *deleted* machines afterwards for being
unconnectable — and since deleting a machine also drops its flows, the routing
failure vanished from the routing denominator and reappeared as a placement
failure. The notebook's own `all_placed` boolean said `True` while the graded
gate said 0.96. Mis-attribution, not just double-counting.

Fixed on both sides:

- `placement` adds `machines_removed` back, so it measures what the decoder
  achieved: **1.00 whenever nothing failed to place.**
- `routing` is scored against `flows_demanded` — the flow count as originally
  derived, captured before pruning — so a connection "solved" by deleting one of
  its machines still counts as unrouted.

```
 rate  genes  blf failed  pruned  demand  routed |   place  route
 0.05     14           0       0      14      14 |    1.00   1.00
 0.15     24           0       1      27      24 |    1.00   0.89
 0.30     34           0       4      40      27 |    1.00   0.68
 0.50     56           0       6      66      42 |    1.00   0.64
```

`zpf_recovery` results carry the base's `machines_removed` so pre- and post-bomb
are measured identically — otherwise the bomb appeared to lose machines it never
touched (post-bomb `place` read 0.79 against a pre-bomb 1.00).

**This lowers reported feasibility, and it changes which layouts win.** The
earlier 98.1% candidate was inflated: its pruned machines were being credited to
routing-success. Numbers from before this fix are not comparable with numbers
after it — re-run anything you intend to quote.

### `main_unit` / `singleton` — partly addressed

`singleton` appears three times in the notebook: the field definition,
`singleton=True` on `main_unit`, and a print that renders `[SINGLETON]` in the
catalogue table. Nothing reads it. No code asserts that a `main_unit` exists or
that there is exactly one.

This is now less dangerous — a `main_unit` caught in the ring returns to its
original position rather than being relocated or lost — but a `main_unit`
sitting in the **crater** must relocate, and if the 9×9 does not fit inside the
circle it is dropped. The factory then has no I/O source at all, every Stage 2
import flow disappears, and the only signal is `feasible=False` plus an entry in
`unplaced_ids`. Worth a hard assertion.

### ~~Recovery re-derives the flow matrix~~ — FIXED (`ZPF_PRESERVE_FLOWS`)

`zpf_recovery` called `derive_flow_matrix(placed)` on every evaluation. That
matcher is greedy and **order-dependent**, and recovery returns `placed` in a
different order (stable machines first, then movable) — so the pairings changed
*even when the bomb destroyed nothing and moved nothing*.

Demonstrated on a 14-machine layout with a crater positioned so it touched no
machine at all:

```
identical machine positions : True   (0 moved, 0 destroyed)
flow pairings identical     : False  (4 dropped, 4 new)
   lost: fitting_unit_0 -> packaging_unit_0    new: fitting_unit_1 -> packaging_unit_0
   lost: refining_unit_0 -> fitting_unit_0     new: refining_unit_0 -> fitting_unit_1
routed 14 -> 12,  feasibility 100% -> 96%
```

The same experiment on the GA notebook moved feasibility **69% → 82%** — a
13-point "improvement" from a bomb that did nothing. That is the "better after
being bombed" effect, in both directions, and it is pure matcher noise.

`CFG.ZPF_PRESERVE_FLOWS` (default **True**) carries the pre-bomb pairings
through recovery and re-routes only the belts, dropping flows whose endpoints
did not survive. Verified on both notebooks:

```
                        positions   pairings   routed        feasibility
SA  PRESERVE=False        identical  CHANGED   14 -> 12      100% -> 96%
SA  PRESERVE=True         identical  identical 14 -> 14      100% -> 100%
GA  PRESERVE=False        identical  CHANGED    9 -> 14       69% -> 82%
GA  PRESERVE=True         identical  identical  9 ->  9       69% -> 69%
```

Effect on a real quick run — regret stops being noise:

| | before | after |
|---|---|---|
| Layout #1 post-bomb feasibility | 94.3% (**up** 1.6) | 71.9% (**down** 20.8) |
| Layout #1 regret | 3.2616 | 0.8385 |
| Layout #2 post-bomb feasibility | 75.5% (**up** 5.9) | 67.9% (**down** 1.7) |
| Layout #2 regret | 0.0000 | 0.0712 |

Both layouts now degrade under bombing, as they should, and both report non-zero
regret. Set `False` if you want the factory to be allowed to re-plan which
machine feeds which after damage — but pre/post are then not comparable, and
regret should not be quoted.

### `ensure_full_connectivity` does not run during recovery

The "every machine with I/O nodes must have a connection" rule is enforced only
in Phase 3. Recovery runs `derive_flow_matrix` → `route_belts` → port-retry →
`repair_feasibility`, but never the bidirectional sweep and never
`connect_or_remove_unlinked`. Recovery also hardcodes
`paths_found == len(flows)`, ignoring `CFG.REQUIRE_FULL_ROUTING` — stricter
than the main path.

### Other open items

- **Rotation is never searched.** Every chromosome is `Rotation.R0`. Since
  rotation decides which face carries the I/O ports, this is a fixed dimension
  of the problem — state it rather than implying otherwise.
- `build_cost` (objective 0) sums incommensurable materials — `ori_ore` +
  `ame_part` + `carbon` into one scalar.
- `_calculate_revenue` excludes cyclic subgraphs from `topo`, so
  planting ↔ seed-picking loops keep `efficiency = 1.0` and are credited full
  revenue regardless of connectivity.
- `_feasibility_ratio` returns `sustain_ratio = 1.0` when `chain_time == 0`, so
  a layout with no routed flows scores a perfect sustainability sub-score.
- The Phase 6 "post-bomb" panel calls `derive_flow_matrix` from scratch on the
  survivors, producing a different pairing than the layout it's compared
  against — the panel isn't a measurement of what the bomb did.
- `_chain_time`'s cycle fallback iterates `min(len(remaining), 10)` times with no
  convergence test; `arrival` grows monotonically, so cyclic `chain_time` is an
  artefact of the iteration count.
- Doc drift: "50×50 grid" (it's 70×70), "Gate 2 ≤ 50 ticks" (it's 300),
  "we have 11 machines" (`MAX_MACHINES=160`).

---

## Part 2b — The `RIGOUR` switch

Both notebooks now open the config cell with:

```python
RIGOUR = "quick"     # or "full"
```

`"quick"` overrides the config after `CFG = FLPConfig()` and prints a banner.
`"full"` leaves every value at its thesis setting. Anything else raises.

| Knob | full | quick |
|---|---|---|
| `POP_SIZE` / `NGEN` | 200 / 50 | 10 / 2 |
| `MAX_MACHINES` | 160 | 40 |
| `ALNS_MAX_ITERS` / `TABU_MAX_ITERS` | 30 / 15 | 2 / 2 |
| `PHASE2_CANDIDATES` | 20 | 3 |
| `PHASE4_TOP_N` | 10 | 2 |
| `SIM_TOP_N` / `SIM_MAX_TICKS` | 3 / 400 | 2 / 150 |
| `ZPF_ITERATIONS` | 620 (GA) / 500 (SA) | 18 / 20 |
| terminal-rate band | 0.15 – 0.45 | 0.02 – 0.06 |
| `MULTIPROCESSING` | True | False |
| `RECONNECT_MAX_PASSES` | 3 | 1 |

Two knobs that were hardcoded are now config-driven: Phase 2's `[:20]` became
`CFG.PHASE2_CANDIDATES`, and `top_10 = refined[:10]` became
`top_layouts = refined[:CFG.PHASE4_TOP_N]` (renamed, since it is no longer
necessarily ten).

**What a quick run does and does not tell you.** It verifies the pipeline
executes end to end and that every phase emits its output — that is genuinely
worth having after a refactor this size. It tells you nothing about solution
quality. POP=10/NGEN=2 is far below what NSGA-II needs to converge, and the
narrowed rate band deliberately keeps BOMs at ~10 machines, which is a different
problem from the ~160-machine case (routing failures at scale are a
grid-congestion problem, not a search-depth one). Do not quote numbers from a
quick run.

The dominant runtime driver is BOM size, not population: `evaluate_layout` is
~3s for a 10-machine BOM and ~17s for 18 machines. Phase 2's `repair=True` path
costs roughly 60s per candidate. Budget accordingly before raising anything.

`MULTIPROCESSING=False` in quick mode is deliberate — tiny populations gain
nothing from workers, joblib swallows tracebacks (the opposite of what a smoke
test needs), and single-process makes the run bit-reproducible from
`RANDOM_SEED` now that the rng threading is fixed.

---

## Part 3 — Performance (2.71× faster, results bit-identical)

Profiling one `evaluate_layout` on a 34-machine BOM put **13.8s of 15.2s inside
`astar()`** — 1,252 calls, 2.0M `in_bounds()` and 683k `is_routable()` calls.
Most of that was searches that were always going to fail: when no path exists,
A\* expands every reachable cell before returning `None`.

Three behaviour-preserving changes:

1. **Reachability pre-check.** `FactoryGrid` now caches connected-component
   labels over the routable cells. If start and goal are in different
   components, A\* returns `None` in O(1) instead of exhausting the grid.
   Sound because the labels ignore belt axis rules, making them an *optimistic*
   bound — they can prove impossibility, never possibility. Invalidated on
   machine placement/removal only; `place_belt` turns `EMPTY` into `BELT`, both
   routable, so it cannot change connectivity.
2. **Flat-array A\* interior.** `g_score`/`came_from` are lists indexed by
   `y*W+x` and `closed` is a `bytearray`, replacing dicts and sets keyed by
   `(x, y)` tuples. Same expansion order, same tie-breaking (the push counter
   sequence is unchanged), same returned path — just no tuple hashing.
3. **`derive_flow_matrix` index.** Five `next((p for p in placed_machines if
   p.instance_id == X), None)` linear scans inside the matching loops replaced
   with one `{instance_id: machine}` dict.

Plus: `route_belts` no longer retries the preferred port pair inside its
fallback loop.

**Verification.** Eight scenarios (both notebooks × two BOM sizes × layout and
recovery), comparing an MD5 of every machine coordinate and every routed path
length, plus MHC, path counts, chain time, revenue, recovery cost and the
relocation penalty:

```
OK  GA rate0.05         4.37s ->  1.76s  (2.48x)
OK  GA rate0.05 recovery 14.81s ->  5.22s  (2.84x)
OK  GA rate0.15          8.33s ->  3.40s  (2.45x)
OK  GA rate0.15 recovery 32.21s -> 11.75s  (2.74x)
OK  SA rate0.05          5.49s ->  1.66s  (3.31x)
OK  SA rate0.05 recovery 21.00s ->  7.15s  (2.94x)
OK  SA rate0.15          7.91s ->  3.40s  (2.33x)
OK  SA rate0.15 recovery 36.98s -> 14.00s  (2.64x)

mismatches: 0        TOTAL 131.1s -> 48.3s        2.71x
```

Every signature identical. No solution quality was traded.

### Where the remaining time goes

After the changes, A\* is 4.8s of 5.9s and it is now genuine search — the
component check showed most failures are *reachable but axis-blocked*, not
disconnected.

**Phase 2 is the real bottleneck for a full run, not the GA.** It calls
`evaluate_layout(repair=True, alns_iters=ALNS_MAX_ITERS*3,
tabu_iters=TABU_MAX_ITERS*2)`, and every ALNS/Tabu iteration is a complete
decode + route. At full settings that is `20 candidates × (90 + 30 + 1) = 2,420`
full decodes. Measured in quick mode: 139s for 3 candidates at 11 decodes each.

The notebook's own `FLPConfig` comment already says:

> *raising these further has sharply diminishing returns above ~10 iterations —
> tested directly on a 158-machine BOM, routing only moved from 63/115 to
> 67/115 going from 5 to 40 iterations.*

`ALNS_MAX_ITERS = 30` (×3 = 90 in Phase 2) sits well past that documented point.
**Dropping it to 10 should cut Phase 2 roughly threefold at, by your own
measurement, negligible quality cost.** That is the single largest remaining
win and it costs nothing structural.

### Further options, each with a real trade-off

| Lever | Gain | Cost |
|---|---|---|
| `CFG.MULTIPROCESSING = True` | near-linear in cores | none to quality; workers seed independently, so set `N_JOBS=1` if you need a bit-reproducible run |
| `ALNS_MAX_ITERS` 30 → 10 | ~3× on Phase 2 | negligible per the config's own benchmark |
| `PHASE2_CANDIDATES` 20 → 10 | 2× on Phase 2 | fewer polished candidates to choose from |
| Cap port-pair attempts in `route_belts` | large | **may miss routes** — changes results |
| Multi-target A\* (one search per out-port) | ~4-6× on routing | changes tie-breaking between equal-length paths |

The last two were deliberately **not** applied: both change output, and the
brief was speed without sacrificing quality.

---

## Part 4 — Runtime

Measured after the fixes: `evaluate_layout(repair=False)` is ~3s for a
10-machine BOM, ~17s for 18 machines, and scales steeply with congestion. At
`POP_SIZE=200 × NGEN=50` (10,200 evaluations) a full run is many CPU-hours.

Before a real run, consider:

1. `derive_flow_matrix` does `next(p for p in placed if p.instance_id == ...)`
   inside nested loops — build one `{instance_id: pm}` dict up front. It's
   called from `derive_topology` inside every `blf_decode` too.
2. `derive_topology` builds a full mock decode + flow matrix on every
   `blf_decode` call; cache it per chromosome.
3. Keep `CFG.MULTIPROCESSING = True` for the real run — but note reproducibility
   now depends on the rng threading (fix #4), and joblib workers still seed
   independently, so set `N_JOBS=1` if you need a bit-reproducible run for the
   thesis.

---

## Note on overwritten files

My verification run wrote real matplotlib output into this folder. I deleted the
three files I created (`v4_sim_*.png`), but two pre-existing figures were
**overwritten with toy-run data** and could not be restored:

- `v4_nsga2_dashboard.png`
- `v4_layout_best_partial_1_sequence.png`

Regenerate both from a real run. All other `v4_layout_*` / `v4_zpf_*` PNGs are
untouched.
