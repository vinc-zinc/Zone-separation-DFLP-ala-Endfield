# Pool rework — status

New files, forked from the `_fixed` notebooks with outputs cleared:

- `flp_definitive_GA_ALNS_pool.ipynb`
- `flp_definitive_SA_ALNS_pool.ipynb`

The `_fixed` notebooks remain the reference and the comparison baseline: they
keep the old 1:1 flow matching and the non-self-fuelling BOM deliberately, so
that the pool model has something to be compared *against*.

---

## What the pool fork implements

### Stage A — logistics build costs

`stash`, `depot_loader` and `depot_unloader` shipped with `build_cost=[]`, i.e.
free. Now driven by `CFG.LOGISTICS_BUILD_COST`.

**These figures are an analogy, not data.** `database.xlsx` prices machines in
its `machine_mat` column and that column covers **production machines only** —
there is no build cost in the source for any of the three. The `rules` sheet
prices their *power* ("all utilities use 10 power each except batteries, belts,
depot unloader and loader") and says nothing about construction. So the earlier
note in this file ("replace with the real figures from database.xlsx") describes
something that cannot be done: there are no such figures.

The values used are keyed to footprint: a stash is 3×3, the same class as the
Refining / Shredding / Fitting / Moulding units, which the database prices at
5–10 units of an early-chain material; the depots get half a stash on the
grounds that they are edge-only and hold nothing. **This needs a sentence in the
methodology chapter.** `LOGISTICS_BUILD_COST = ()` makes them free again, which
is what the source model literally specifies.

### Stage A — self-fuelling power

Thermal-bank fuel demand feeds back through the BOM expansion as a fixed point
(`CFG.SELF_FUEL_POWER`, `CFG.BOM_POWER_PASSES`). The factory manufactures the
batteries it burns instead of drawing them from nothing.

```
 rate  self_fuel   BOM  banks  makes HC_bat?  build_cost
 0.15      False    24      1          False         207
 0.15       True    56      1           True         453
 0.30      False    34      1          False         291
 0.30       True    66      1           True         537
```

### Stage B — rate-aware matching + global pool

`derive_flow_matrix` rewritten:

- **Stage 1** matches producers to consumers **by rate**. A consumer keeps
  drawing from further producers until its per-tick demand is met, so a
  packaging unit needing 1 ferri_part/tick is fed by the two fitting units that
  supply 0.5 each. This is what closes P1.
- **Stage 2** withdraws any still-unmet demand from the **nearest** pool source.
- **Stage 3** deposits any unallocated supply at the **nearest** pool sink.
- `intensity` is now the actual per-tick rate carried.

`pool_balance(placed, flows, routed=None)` reports, per internal material,
`deposited / withdrawn / deficit`. `RAW_MATERIALS` is derived from the catalogue
(nothing produces them) and exempt: `ame_ore, ferri_ore, ori_ore, LC_W_bat,
SC_W_bat`.

### Measured effect of the pool

```
 rate variant   BOM  placed  flows   routed  route%     MHC   feas
 0.15   fixed    24      23     24    24/24    100%    1056   96%
 0.15   pool     56      32     32    28/32     88%     386   86%
 0.30   fixed    34      30     30    27/30     90%    1357   67%
 0.30   pool     66      34     34    28/34     82%     381   84%
```

**MHC falls ~3.5×** — short hops to a nearby depot instead of long
cross-factory belts, which is the whole point of the pool.

---

## What was wrong with the fork itself

The pool notebooks were branched from a `_fixed` that predates the G1 and R0
work, so they had silently lost four fixes. All four are now ported:

- **`_calculate_revenue` took `min()` over surviving inputs**, so destroying a
  supplier removed that input from the minimum and the consumer's efficiency
  went *up*. Bombing could raise the reported rate. This was a direct cause of
  the fork's `regret = 0.0000`.
- **the `MAX_MACHINES` priority tail** was still in the genome (70% of it, of
  which one uniform crossover preserved 5% of the resulting placement order).
  Build order now comes from `_order_instances`.
- **candidates were not de-duplicated** by the layout they encode.
- **Phase 4 fired a single bomb** at the fixed `CFG.ZPF_X/ZPF_Y` instead of a
  rejection-sampled scenario set.

Plus everything from the same session's work on both families: the position-based
recovery neighbourhood (R4), the un-recovered post-bomb baseline and the clean
re-route reference (R1), the normalised sustain gate (P6), net-output revenue
(P2), rotation search (P7) and the P9 cleanups. See `PROBLEM_REGISTER.md`.

---

## "The bomb improves the factory" — resolved, and what it actually was

The earlier reading was that `sustain` recovers because destroying machines
shortens the critical path. That was one of three causes, and the smallest.

1. **`sustain` rewarded destruction.** `SIM_EQ_MAX_TICKS / chain_time` falls as
   machines are added. Fixed: the budget now scales with the layout's own
   irreducible processing time (`CFG.SUSTAIN_NORMALISE`), so removing a machine
   shortens numerator and denominator together.
2. **The routing gate rewarded destruction.** Post-bomb routing was scored
   against the *surviving* flow count while pre-bomb was scored against the full
   derived demand, so deleting a machine deleted its unroutable flows from the
   denominator. Fixed: `_zpf_flow_demand()` holds the denominator at the
   pre-bomb demand.
3. **The pre-bomb rate was never comparable.** The recovery re-lays every belt
   at once on a fresh grid; the pre-bomb belts were laid incrementally by five
   successive passes. On this fork the un-recovered post-bomb layout scored
   **6.20 against a pre-bomb 3.17** — destroying two machines appeared to double
   revenue, purely because a less congested grid routed flows the incremental
   process never managed. Fixed: Phase 4 computes `post_bomb_state(result, None)`
   — the same layout, undamaged, through the same fresh-grid re-route — and
   reports the re-route effect separately from the damage.

Phase 4 now counts and warns about any scenario where the un-recovered layout
beats the reference, so this class of defect cannot go quiet again.

---

## Known issues — next session

**1. Stashes are barely used.** Of 7 built, 7 had no flow at all.

Rate-aware Stage 1 satisfies internal demand directly, so there is little
surplus left to deposit. The pool is mostly carrying *raw imports in* and
*finished product out*, which is arguably correct — but `EXPORT_STASHES = 0.15`
now over-provisions, and unused stashes are built, costed and then pruned.

*Action:* lower `EXPORT_STASHES` substantially, or size it from the number of
Stage-3 deposit flows rather than from BOM size.

**2. Pool flows route poorly.**

```
deposit flows   0/3  routed
withdraw flows  9/20 routed
direct flows   26/38 routed
```

Withdrawals are the weak point. Depots are edge-only, so they sit on the
boundary while consumers are in the middle — long paths through congested space.
Worth trying: more, smaller depots; or letting a machine withdraw from *any*
source rather than only the nearest.

**3. `pool_balance` shows a real deficit.** A run showed
`utility_supply: deposited 0.0, withdrawn 1.0` — something draws it from the
pool and nothing deposits it. Phase 2 now *prints* any per-material deficit;
whether it becomes a hard gate is still open.

**4. The starvation cascade dominates this fork.** On the SA quick profile a
single destroyed machine takes the rate from 10.11 to 3.20. That is
`CFG.STARVED_INPUT_EFF` propagating, not the crater. The principled fix (P3
option 1 — penalty proportional to the *shortfall* rather than a flat 0.01) is
now unblocked here, because this fork's flows carry real per-tick rates. This is
the highest-value remaining change on the pool side.

---

## Suggested order next time

1. **P3 option 1** — shortfall-proportional starvation, using the rates Stage 1
   already computes (issue 4). Everything downstream of revenue is currently
   dominated by a flat magic constant.
2. Re-tune `EXPORT_STASHES` / `IMPORT_DEPOTS` for the new flow structure (1).
3. Improve withdrawal routing (2).
4. Decide whether the `pool_balance` deficit becomes a hard gate (3).
5. Write the build-cost analogy into the methodology chapter, since it cannot be
   sourced from the database.
