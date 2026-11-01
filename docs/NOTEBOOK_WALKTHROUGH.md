# What the notebook does, in order

Reference for `flp_definitive_GA_ALNS_fixed.ipynb` and
`flp_definitive_SA_ALNS_fixed.ipynb`. The two are **identical code except the
config cell and the recovery cell** — Phase 1 to Phase 3 and Phase 5 to Phase 6
are the same in both. Only `zpf_recovery` differs: NSGA-II in the GA notebook,
simulated annealing in the SA one. The `_pool` forks add a global logistics pool
and self-fuelling power on top.

Two things run top to bottom: a **setup half** (cells 1–35) that defines the
model, and a **pipeline half** (cells 36–44) that executes six phases. Nothing
in the setup half does work; every cell there ends in a one-line confirmation so
a stalled run is obvious.

---

## Part A — the setup half

### §1 Constants (cell 2)

`NON_CONVEYED_MATERIALS = {'power'}` and `BATTERY_POWER`, the power yield of each
battery type. Power is produced by a recipe but never rides a belt, so it must be
excluded from the flow matrix or every thermal bank demands an impossible
conveyor.

*Output:* `Machine data tables loaded.`

### §1.5 Control Panel (cell 4)

Every tunable parameter for every phase, in one `FLPConfig` dataclass, plus the
`RIGOUR` switch.

- `RIGOUR = "quick"` overrides ~15 knobs for a ~5-minute smoke test. It proves
  the pipeline executes; it says nothing about solution quality and its numbers
  must never be quoted.
- `RIGOUR = "full"` uses the dataclass defaults.

Grouped by phase: geometry, GA search, layout repair, ZPF disruption, power,
simulation, feasibility weights, revenue attribution.

*Output:* the configuration banner — grid, belt speed, search sizes, repair
budgets, phase widths, ZPF geometry, power settings. **Read this first in any
result notebook**; it is the only record of what produced the numbers below it.

### §2–§3 Enums and data classes (cells 6, 8)

`Rotation`, `TileState`; then `Recipe`, `MachineType`, `PlacedMachine`,
`FlowPair`. A `MachineType` carries footprint, power cost, edge-only flag,
`singleton` flag, `is_power_src`, and its list of recipes. A `PlacedMachine` is a
type plus coordinates, rotation, instance id and active recipe index.

### §4 Machine catalogue (cell 10)

14 machine types built from the recipe tables, plus `REVENUE_TABLE`, plus
`IO_SOURCE_IDS = (main_unit, depot_unloader)` and `IO_SINK_IDS`.

Then two derived sets, and the distinction between them matters:

- `RAW_MATERIALS = {ame_ore, ferri_ore, ori_ore}` — ores accumulate at a fixed
  rate, so they are the one class of input a layout may draw from the boundary
  without building anything.
- `UNOBTAINABLE = {LC_W_bat, SC_W_bat}` — consumed by a recipe, produced by
  nothing, and not ores. Recipes needing them are dead.

Plants are neither: `planting_unit` and `seed_picking_unit` form a closed
doubling loop (seed → 2 plant → 4 seed), so they are produced.

*Output:* the catalogue table, then the two sets.

### §5 Flow matrix (cell 12)

`derive_flow_matrix(placed)` decides who supplies whom. It walks each machine's
recipe inputs and matches them to producers, skipping `NON_CONVEYED_MATERIALS`.
The `_fixed` fork uses a greedy 1:1 match; the `_pool` fork matches **by rate**
and routes the remainder through a global depot pool.

Output is a list of `FlowPair(src_id, dst_id, material, intensity)` — the demand
the router then has to satisfy.

### §6–§8 Grid, chromosome, decoder (cells 14, 16, 18)

`FactoryGrid` is a `GRID_W × GRID_H` tile array. `can_place` accepts only
`EMPTY`; belts may traverse `EMPTY` or `BELT`. This is what makes a crater
physically respected rather than merely penalised.

A `Chromosome` is a list of `Gene(machine_id, rotation, recipe_idx)`.

`blf_decode` is Bottom-Left-Fill with an **adjacency-biased spiral**: each
machine is placed at the first legal cell found spiralling out from its
preferred anchor, so machines cluster near their flow partners rather than
filling the grid corner-first. Edge-only machines (depot loaders/unloaders) are
constrained to the boundary.

### §9 Routing (cell 20)

`astar` with belt axis-crossing rules — a horizontal belt may cross a vertical
one, but two parallel belts may not occupy the same tile. `route_belts` takes
the flow matrix and returns `[(FlowPair, path_or_None)]`. A `None` path is an
unrouted flow, and that is the single most common reason a layout fails.

### §10.5 Feasibility repair (cell 22)

`find_starved_connections`, `find_unconnected_ther_banks`,
`try_place_depot_unloader_near`, `repair_feasibility`. Spawns a depot next to a
machine whose input nothing supplies. The depot's material is read from the
machine's own recipe, so a bank burning HC_bat gets an HC_bat depot.

### §11 Visualisation (cell 24)

`plot_layout`, `plot_zpf_sequence`, `plot_gantt`, `plot_throughput`. Belts are
coloured by production line, not by material, so a chain is followable by eye.

### §14 Simulation (cells 26–30)

`SimEngine` is a discrete-time simulator: machines consume, process for
`process_time` ticks, emit onto belts; items travel one tile per `BELT_SPEED`
ticks. Machines are tracked as `idle / running / starved / blocked / unpowered`.

`supply_rates` injects boundary materials per tick. `is_equilibrium` requires
output to be stable over a window **and** at least `SIM_MIN_LIVE_FRACTION` of
recipe-bearing machines to have produced — a factory where 90% of machines are
starved is not in equilibrium, it is dead.

### §Scoring (cell 32)

The core of the model.

- **`_chain_time`** — critical path through the production DAG, machine process
  times plus belt travel. Cyclic sub-graphs are iterated rather than recursed.
- **`_sustain_budget`** — the tick budget `chain_time` is scored against, scaled
  to the layout's own irreducible processing time. A flat budget rewarded having
  fewer machines, so a bombed layout scored *better* than the one it came from.
- **`_power_output`** — total generation. A bank counts only if a routed flow
  actually delivers its fuel; an unfuelled bank contributes nothing.
- **`_calculate_revenue`** — revenue per tick, discounted by each machine's
  input-supply efficiency:
  - Efficiency is evaluated against the machine's **recipe requirements**, not
    against whichever flows survived. A required input that no routed flow
    supplies scores `CFG.STARVED_INPUT_EFF` (0.01) and cascades downstream.
  - `CFG.REVENUE_MODE = "net"` credits produced minus consumed per material, so
    an intermediate the factory eats itself is paid for exactly once.
  - With `breakdown=True` it returns the per-material ledger as well.
- **`evaluate_layout`** — decode → flows → route → optionally repair
  (`alns_macro_repair` then `tabu_micro_polish`) → score.
- **`production_report`** — prints that ledger: made/tick, used/tick, net/tick,
  unit price, revenue/tick and share per material, plus how many machines are at
  full rate and which are worst supplied.

### §Feasibility (cell 34)

Four gates, each a ratio in [0,1]:

| gate | meaning |
|---|---|
| `placement` | machines the decoder found room for |
| `routing` | flows routed, **against pre-bomb demand** so deleting a machine cannot raise the score |
| `power` | generation ÷ demand |
| `sustain` | `_sustain_budget` ÷ `chain_time` |

`_feasibility_ratio` combines them under `CFG.FEAS_AGGREGATION`
(`mean` default, or `geometric` / `min`) using weights `W_PLACEMENT`,
`W_ROUTING`, `W_POWER`, `W_SUSTAIN`. **`W_POWER = 0.0`** by default — with one
thermal bank the gate is binary, and a single fuel belt landing or missing moved
the headline 25 points. Zero-weighted gates are *dropped* and the rest
renormalise; `power_ok` is still computed, still printed, and still part of the
hard `feasible` boolean.

**`terminal_rate = revenue × feasibility`** — the number the thesis quotes.

Also here: `derive_rate_balanced_bom` (backward expansion from target rates to a
machine list, with thermal banks sized from total power demand and the fuel
chosen by `choose_power_recipe`), `_order_instances` (deterministic build order —
hub, import depots, production shallowest-first, thermal banks, export sinks),
and `rotation_polish`.

*Output:* the fuel table, showing every `ther_bank` recipe scored as power per
machine of supporting chain, with the chosen one marked.

---

## Part B — the six phases

### Phase 1 — NSGA-II layout generation (cells 36–38)

**Genome:** product rates + recipe multipliers. Nothing else. The old
`MAX_MACHINES` tail of placement priorities was dropped — one uniform crossover
preserved only 5% of the resulting order, so 70% of the genome was noise.

**Objectives (3):** minimise build cost, **maximise terminal_rate**, minimise
material handling cost. Regret is *not* an objective here: this phase builds
layouts, it does not bomb them.

**Per individual:** genome → `derive_rate_balanced_bom` → `_order_instances` →
`Chromosome` → `evaluate_layout(repair=False)` → three objectives. A BOM over
`MAX_MACHINES` gets a penalty that scales with the overage rather than a flat
wall, so the optimiser can approach the cap as a boundary instead of a cliff.

*Output:* one line per generation —

```
Gen  1: Best Rate=1.0076, Cost=295000, MHC=295000 | Avg Rate=0.4839 | front1=4/10 distinct=9 fresh=+0
```

`front1` and `distinct` are the ones to watch. If `front1` reaches the whole
population the non-dominated sort has no selection pressure left and the run is
finished regardless of how many generations remain.

Then `v4_nsga2_dashboard.png` — convergence curves and the Pareto front.

### Phase 2 — feasibility polish (cell 39)

Takes the top `PHASE2_CANDIDATES` from the **ranked** population, de-duplicated
by the layout each individual encodes (a real run produced 20 candidates
encoding only 9 distinct layouts). Each is re-evaluated with `repair=True`, so
ALNS macro-repair and Tabu micro-polish actually run, then `rotation_polish`
tries alternative rotations on the worst-connected machines.

*Output:*

```
  3 distinct layouts selected from 10 individuals
    rotation polish: feas 0.937 -> 0.939, MHC 1217 -> 1174
  Candidate  1: Rate=3.2982, Cost=130, MHC=1174, Feasibility=93.9% [FEASIBLE]
                 gates: place 1.00 route 0.49 power 0.00 sust 1.00  (placed 85/118, routed 67/80)
```

The `gates:` line is essential — the headline percentage alone cannot tell you
whether a layout is short of space, short of belts, or short of power.

### Phase 3 — connection deep polish (cell 40)

`connect_deep_polish`, then `ripup_and_reroute` (a blocked flow may evict an
existing belt and re-lay both — the standard VLSI detailed-routing move), then
`ensure_full_connectivity`, which enforces that every machine with an input node
has an incoming belt and every machine with an output node has an outgoing one.

*Output:* a connectivity census, per-pass improvements, and the final ranking
that decides which layouts get bombed. Feasible layouts are named
`v4_layout_top_N_*`, partial ones `v4_layout_best_partial_N_*`.

### Phase 4 — ZPF disruption and recovery (cell 41)

The contribution. For each of the top `PHASE4_TOP_N` layouts:

1. **Scenarios.** `make_bomb_scenarios` samples crater positions uniformly and
   **rejects any that destroy nothing**, repeating until `ZPF_SCENARIOS` valid
   craters are found. Seeded from the layout, so GA and SA face identical
   craters on identical layouts. Uniform-then-reject keeps the unbiased
   geometry — dense clusters and large footprints are hit more often, as a real
   accident would be — unlike centring on a random machine, which over-samples
   isolated ones.

2. **Zones.** A crater rectangle, then `r1` (flexible), `r2` (penalty), and
   everything beyond (stable/frozen). Machines in the crater are destroyed.
   Machines in the rings *may* move but are charged an avoidable-relocation
   penalty scaled by their original distance from the blast — a small disruption
   must not justify rearranging the far side of the factory. Machines outside
   `r2` are frozen; only belts may change there.

3. **Three states per scenario**, not two:
   - `pre` — before the bomb
   - `post_bomb` — `post_bomb_state()`: crater blocked, its machines gone,
     everything else exactly where it was, belts re-routed, pre-bomb supply plan
     carried over. Deliberately *without* recovery repair.
   - `post_recovery` — after `zpf_recovery`

4. **Recovery.** `ZPFNeighbourhood` is a destroy-and-reinsert operator set over
   **coordinates** — `random`, `greedy`, `shift`, `restore`, `swap`, `rotate`,
   `order`. A solution is `(order, anchors, rotations)`. Both notebooks use the
   same neighbourhood; only the search strategy differs (NSGA-II vs annealing),
   which is what makes the comparison about the strategy. Individual 0 / the
   SA's starting incumbent is the deterministic repair, so the search can never
   return something worse than the heuristic it replaces.

5. **Metrics.** `recovery_metrics` gives three, because one is not enough:
   - `regret = pre − post_recovery` — what the thesis quotes
   - `gain = post_recovery − post_bomb` — what the recovery actually contributed
   - `frac = gain ÷ (ref − post_bomb)` — normalised, comparable across layouts

*Output, per scenario:*

```
  # 1 crater(13,39) destroyed=1 movable=5  rate 3.5000 -> 0.4405 -> 3.5000
                                  regret= 0.0000  gain=+3.0595  frac=100.0%
```

then a per-layout regret and recovery distribution, the effort log
(evaluations, evals-to-best, distinct costs, whether it stopped early), and a
cross-layout summary table. Finally:

```
Crater integrity: 12 state(s) checked, 0 violations
```

asserted per scenario — no machine footprint and no belt tile may intersect the
crater.

**Phase 5 and 6 carry the WORST scenario forward.** A resilience claim should be
made against the hardest case, not a lucky one.

### Phase 5 — discrete-time simulation (cell 43)

Runs `SimEngine` on the pre-bomb and post-recovery layouts. This is the
independent check on the analytic model: Phase 1–4 assume machines run at rated
rate whenever their inputs exist, and the simulation does not.

*Output:* per layout, machine and belt counts, equilibrium tick, how many
machines ever ran, how many are starved at the end, simulated revenue per tick,
live fraction, power demand and brownout ticks. Then the per-item ledger beside
the **simulated** throughput, so a static rate the simulation fails to reproduce
appears as a specific material at 0% rather than as two totals that disagree.

Figures: `v4_sim_gantt_layout_N.png` (per-machine status over time),
`v4_sim_throughput_layout_N.png`, `v4_sim_regret_summary.png`.

Ends with a summary table comparing analytic rate against simulated throughput,
and a consistency verdict.

### Phase 6 — layout figures (cell 44)

`plot_zpf_sequence` — three panels side by side: **pre-bomb | post-bomb |
post-recovery**, all drawn with the crater and both rings at the scenario's
actual coordinates, captioned with those coordinates, the damage counts and the
regret.

*Output:* `v4_layout_top_N_sequence.png` / `v4_layout_best_partial_N_sequence.png`.

---

## Reading a result notebook

In order:

1. **Config banner** — was this `full` or `quick`? Quick numbers are not results.
2. **Fuel table** — which battery the banks burn, and why.
3. **Phase 1 `front1` / `distinct`** — did the GA actually search?
4. **Phase 2/3 `gates:` lines** — which gate is binding.
5. **Phase 4 three-state lines** — regret *and* gain. Regret alone cannot
   distinguish "the bomb missed" from "the recovery worked".
6. **Crater integrity** — must be 0 violations.
7. **Phase 5 analytic vs simulated** — if these disagree by an order of
   magnitude, the analytic rate above them is not defensible.

## Known limitations to state alongside any result

- The recovery searches `(unrouted, MHC + penalties)` while results report
  `revenue × feasibility` (**R5**).
- The `_fixed` fork's BOM does not manufacture its own thermal-bank fuel;
  `check_raw_dependencies` reports it per layout. `_pool` fixes this.
- The grid is 70×70; the source specification says 50×50 (**N1**).
- GA and SA use different `RANDOM_SEED` values (42 / 60), so they generate
  different layouts and the comparison is unpaired.
