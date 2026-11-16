# Zonal Penalty Framework for Disruption-Triggered Partial Recovery in Dynamic Facility Layout Problems

[![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://python.org)
[![Streamlit](https://img.shields.io/badge/Streamlit-Dashboard-red.svg)](https://streamlit.io)
[![License](https://img.shields.io/badge/License-Academic-green.svg)](#license)

> **MSc in Artificial Intelligence — Thesis Project**  
> Asia Pacific University of Technology & Innovation (APU)  
> Vincentius Aditya • Supervised by Assoc. Prof. Dr. Vazeerudeen Hameed • 2026

---

## Overview

This repository contains the source code, experiment notebooks, and Streamlit dashboard for a thesis on **disruption recovery in dynamic facility layout problems (DFLP)** using a novel **Zonal Penalty Framework (ZPF)**.

The system optimises factory floor layouts on a 70×70 discrete grid (modelled after [Factorio](https://factorio.com)), then simulates localised disruptions (e.g. equipment failures, explosions) and evaluates how well different metaheuristic recovery strategies restore production.

### Key Contributions

1. **Zonal Penalty Framework (ZPF)** — A four-zone Euclidean model that encodes disruption severity spatially (crater → flexible → penalty → safe), constraining which machines may be relocated during recovery.
2. **NSGA-II + ALNS pipeline** — Multi-objective layout generation (minimise cost, minimise MHC, maximise throughput) with Adaptive Large Neighbourhood Search repair.
3. **Belt-preserving recovery** — Only belts physically damaged by the crater are re-routed; undamaged conveyors are kept in place, eliminating measurement noise from full re-routing.
4. **Independent SimEngine validation** — A discrete-time tick-by-tick simulation engine that validates analytical throughput estimates against physically simulated production.

---

## Repository Structure

```
├── zpf_core.py                      # Complete engine (3,800+ lines) — all classes,
│                                    #   functions, routing, simulation, DEAP setup
├── streamlit_app.py                 # Streamlit dashboard for interactive visualisation
├── test_fast_run.py                 # Standalone pipeline script (full run)
├── DEMO_ZPF_walkthrough.ipynb       # Curated demo notebook (no kernel needed)
├── Full_Thesis_Formatted.docx       # Final formatted thesis (APU template)
│
├── docs/                            # Documentation, summaries & defect tracking
│   ├── NOTEBOOK_WALKTHROUGH.md      # Guide to navigating experiment notebooks
│   ├── THESIS_SUMMARY.md            # High-level thesis summary
│   ├── PROBLEM_REGISTER.md          # Engineering log of defects found and fixed
│   ├── REVIEW_GA_SA_fixed.md        # GA vs SA comparative review
│   └── POOL_REWORK_STATUS.md        # Technical status notes
│
├── experiments/                     # Raw GA & SA experimental Jupyter notebooks
│   ├── flp_definitive_GA_ALNS*.ipynb
│   └── flp_definitive_SA_ALNS*.ipynb
│
└── archive/                         # Legacy test runners and utility scripts
    ├── test_phase2.py
    ├── test_v6*.py
    └── test_real.py
```

---

## Pipeline Architecture

The optimisation runs in six phases:

| Phase | Name | Description |
|-------|------|-------------|
| **1** | NSGA-II | Multi-objective evolutionary search over layout genotypes |
| **2** | Repair | ALNS destroy-and-reinsert + Tabu polish for placement and routing |
| **3** | Deep Polish | Rip-up-and-reroute blocked flows; connect-or-remove cleanup |
| **4** | ZPF Recovery | Bomb top layouts with random craters; recover via NSGA-II or SA |
| **5** | Simulation | Discrete-time SimEngine validates pre-bomb vs post-recovery throughput |
| **6** | Visualisation | Three-state layout plots, Gantt charts, throughput curves |

---

## Quick Start

### Prerequisites

```bash
pip install -r requirements.txt
```

### Run the Streamlit Dashboard

```bash
streamlit run streamlit_app.py
```

Opens at `http://localhost:8501` with:
- **Configuration panel** — choose rigour profile (quick/full/custom), tune parameters
- **NSGA-II tab** — convergence dashboard, Pareto front visualisation
- **Layout tab** — factory grid with machine placement and belt routing
- **ZPF Recovery tab** — bombing scenarios, regret distribution
- **Simulation tab** — tick-by-tick Gantt charts and throughput curves

### Run a Standalone Pipeline

```bash
python test_fast_run.py
```

This runs the full six-phase pipeline and prints results to stdout.

### View the Demo Notebook

Open `DEMO_ZPF_walkthrough.ipynb` — it contains pre-computed outputs from a thesis-grade run. **No kernel needed** to view the results.

---

## Key Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `GRID_W × GRID_H` | 70 × 70 | Factory grid dimensions (cells) |
| `POP_SIZE` | 200 | NSGA-II population size |
| `NGEN` | 50 | Generations |
| `MAX_MACHINES` | 160 | Hard cap on machines per layout |
| `ZPF_R1` | 5.0 | Flexible zone radius |
| `ZPF_R2` | 12.0 | Penalty zone radius |
| `ZPF_SCENARIOS` | 5 | Bombing scenarios per layout |
| `ZPF_ITERATIONS` | 300 | Recovery evaluation budget |
| `SIM_MAX_TICKS` | 400 | Simulation duration |

Set `RIGOUR = "quick"` for a 5-minute smoke test, or `"full"` for thesis-grade results (several hours).

---

## Results Summary

On the definitive full run (seed 12, 200×50 NSGA-II):

- **5 feasible layouts** generated with 100% placement and routing
- **Recovery regret near zero** — belt preservation eliminated re-routing noise
- **SimEngine validates analytical rates** — simulated throughput matches within 50%+ of analytical estimates
- **GA (NSGA-II) recovery** outperforms SA on convergence speed (fewer evaluations to best)

See [`docs/PROBLEM_REGISTER.md`](docs/PROBLEM_REGISTER.md) for the full engineering log of 16 defects identified and fixed during development.

---

## License

This is academic work submitted as part of a Master's thesis at APU. The code is provided for reference and reproducibility. Please cite appropriately if you build upon this work.

---

## Citation

```
Aditya, V. (2026). Zonal Penalty Framework for Disruption-Triggered Partial
Recovery in Dynamic Facility Layout Problems. MSc Thesis, Asia Pacific
University of Technology & Innovation.
```
