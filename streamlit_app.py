"""
ZPF DFLP Pipeline — Streamlit Dashboard
Wraps the zpf_core engine with an interactive visualization interface.
"""
import streamlit as st
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
import random
import sys
import os
import time

# Add the directory to path so zpf_core can be imported
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import zpf_core
from zpf_core import (
    FLPConfig, FactoryGrid, SimEngine, Rotation, TileState,
    MACHINE_CATALOGUE, GRID_W, GRID_H, MIN_MACHINE_SPACING,
    blf_decode, route_belts, evaluate_fitness, create_config,
    astar, Chromosome, Gene, derive_flow_matrix,
    calculate_metrics, repair_feasibility,
    find_starved_connections, find_unconnected_ther_banks,
    plot_layout, build_belt_paths, find_dag_roots,
)

st.set_page_config(page_title="ZPF DFLP Pipeline", layout="wide", page_icon="🏭")
st.title("🏭 Zonal Penalty Framework — DFLP Optimization Dashboard")

# ============================================================
# SIDEBAR — Configuration
# ============================================================
st.sidebar.header("⚙️ Configuration")

rigour = st.sidebar.selectbox("Rigour Profile", ["quick", "full", "custom"],
                                help="Quick: ~5 min smoke test. Full: thesis-grade run (hours).")
seed = st.sidebar.number_input("Random Seed", value=12, min_value=0, max_value=99999)

# Custom parameters (only shown if custom)
custom_params = {}
if rigour == "custom":
    st.sidebar.subheader("Search Parameters")
    custom_params['POP_SIZE'] = st.sidebar.slider("Population Size", 10, 200, 20)
    custom_params['NGEN'] = st.sidebar.slider("Generations", 2, 50, 5)
    custom_params['MAX_MACHINES'] = st.sidebar.slider("Max Machines", 20, 160, 40)
    
    st.sidebar.subheader("ZPF Parameters")
    custom_params['ZPF_R1'] = st.sidebar.slider("Zone R1 (flexible radius)", 1.0, 15.0, 5.0)
    custom_params['ZPF_R2'] = st.sidebar.slider("Zone R2 (penalty radius)", 5.0, 25.0, 12.0)
    custom_params['ZPF_SCENARIOS'] = st.sidebar.slider("Bombing Scenarios", 1, 10, 3)
    custom_params['ZPF_ITERATIONS'] = st.sidebar.slider("Recovery Budget", 10, 300, 50)
    
    st.sidebar.subheader("Repair")
    custom_params['ALNS_MAX_ITERS'] = st.sidebar.slider("ALNS Iterations", 1, 30, 5)
    custom_params['TABU_MAX_ITERS'] = st.sidebar.slider("Tabu Iterations", 1, 15, 5)
    
    st.sidebar.subheader("Simulation")
    custom_params['SIM_MAX_TICKS'] = st.sidebar.slider("Sim Max Ticks", 50, 400, 150)
    custom_params['MULTIPROCESSING'] = st.sidebar.checkbox("Multiprocessing", value=False)

run_btn = st.sidebar.button("🚀 Run Pipeline", type="primary", use_container_width=True)

# ============================================================
# TABS
# ============================================================
tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "📋 Configuration", "📈 NSGA-II", "🗺️ Layouts", "💥 ZPF Recovery", "🔬 Simulation"
])

# ── Tab 1: Configuration Summary ──
with tab1:
    st.header("Configuration Summary")
    cfg = create_config(rigour=rigour, seed=seed, **custom_params)
    
    col1, col2, col3 = st.columns(3)
    with col1:
        st.subheader("Factory Grid")
        st.metric("Grid Size", f"{GRID_W} × {GRID_H}")
        st.metric("Max Machines", cfg.MAX_MACHINES)
        st.metric("Machine Spacing", MIN_MACHINE_SPACING)
    
    with col2:
        st.subheader("NSGA-II Search")
        st.metric("Population", cfg.POP_SIZE)
        st.metric("Generations", cfg.NGEN)
        st.metric("Rate Band", f"{cfg.MIN_TERMINAL_RATE} – {cfg.MAX_TERMINAL_RATE}")
    
    with col3:
        st.subheader("ZPF Disruption")
        st.metric("Crater Size", f"{cfg.ZPF_W} × {cfg.ZPF_H}")
        st.metric("Zone R1 / R2", f"{cfg.ZPF_R1} / {cfg.ZPF_R2}")
        st.metric("Recovery Budget", cfg.ZPF_ITERATIONS)
    
    # Factory grid preview with zone overlay
    st.subheader("Factory Grid Preview (Zone Overlay)")
    fig_grid, ax_grid = plt.subplots(1, 1, figsize=(8, 8))
    ax_grid.set_xlim(0, GRID_W)
    ax_grid.set_ylim(0, GRID_H)
    ax_grid.set_aspect('equal')
    ax_grid.set_title(f"70×70 Grid with ZPF Zones at ({cfg.ZPF_X}, {cfg.ZPF_Y})")
    ax_grid.grid(alpha=0.1)
    
    # Draw crater
    crater = mpatches.Rectangle((cfg.ZPF_X, cfg.ZPF_Y), cfg.ZPF_W, cfg.ZPF_H,
                                  fill=True, facecolor='red', alpha=0.6, edgecolor='darkred', lw=2)
    ax_grid.add_patch(crater)
    
    # Draw zone rings
    cx, cy = cfg.ZPF_X + cfg.ZPF_W/2, cfg.ZPF_Y + cfg.ZPF_H/2
    r1_circle = mpatches.Circle((cx, cy), cfg.ZPF_R1, fill=False, edgecolor='orange', lw=2, ls='--',
                                  label=f'R1={cfg.ZPF_R1} (Flexible)')
    r2_circle = mpatches.Circle((cx, cy), cfg.ZPF_R2, fill=False, edgecolor='blue', lw=2, ls=':',
                                  label=f'R2={cfg.ZPF_R2} (Penalty)')
    ax_grid.add_patch(r1_circle)
    ax_grid.add_patch(r2_circle)
    ax_grid.legend(loc='upper right')
    
    st.pyplot(fig_grid)
    plt.close(fig_grid)
    
    # Machine catalogue
    with st.expander("Machine Catalogue"):
        cat_data = []
        for name, m in MACHINE_CATALOGUE.items():
            for i, r in enumerate(m.recipes):
                cat_data.append({
                    "Machine": name, "Recipe": i,
                    "Size": f"{m.width}×{m.height}",
                    "Inputs": ", ".join(f"{mat}×{q}" for mat, q in r.inputs),
                    "Outputs": ", ".join(f"{mat}×{q}" for mat, q in r.outputs),
                    "Time": r.process_time
                })
        st.dataframe(cat_data, use_container_width=True)

    # Full config
    with st.expander("Full Configuration (all parameters)"):
        st.json({k: str(v) if not isinstance(v, (int, float, bool, str)) else v 
                 for k, v in cfg.__dict__.items()})

# ── Run Pipeline ──
if run_btn:
    st.session_state['running'] = True
    st.session_state['cfg'] = cfg
    
    # Initialize globals needed by the engine
    random.seed(cfg.RANDOM_SEED)
    np.random.seed(cfg.RANDOM_SEED)
    zpf_core.CFG = cfg
    zpf_core.SIM_EQ_MAX_TICKS = cfg.SIM_EQ_MAX_TICKS
    zpf_core.BLF_VERBOSE = cfg.SHOW_BLF_WARNINGS
    zpf_core.POP_SIZE = cfg.POP_SIZE
    zpf_core.NGEN = cfg.NGEN
    zpf_core.CXPB = cfg.CXPB
    zpf_core.MUTPB = cfg.MUTPB
    zpf_core.MAX_MACHINES = cfg.MAX_MACHINES
    
    with tab2:
        st.header("NSGA-II Optimization")
        st.info(f"Running NSGA-II: Pop={cfg.POP_SIZE}, Gen={cfg.NGEN}, MaxMachines={cfg.MAX_MACHINES}")
        
        progress_bar = st.progress(0, text="Initializing population...")
        status_text = st.empty()
        
        # Check if run_nsga2 exists and is callable
        if hasattr(zpf_core, 'run_nsga2'):
            try:
                with st.spinner("Running NSGA-II optimization..."):
                    start_time = time.time()
                    final_pop, conv_history = zpf_core.run_nsga2()
                    elapsed = time.time() - start_time
                
                st.session_state['final_pop'] = final_pop
                st.session_state['conv_history'] = conv_history
                
                st.success(f"✅ NSGA-II complete in {elapsed:.1f}s — {len(final_pop)} individuals")
                
                # Convergence Dashboard
                st.subheader("Convergence Dashboard")
                fig, axes = plt.subplots(2, 2, figsize=(14, 10))
                fig.suptitle('NSGA-II Optimization Dashboard', fontsize=14, fontweight='bold')
                
                # Terminal Rate
                ax = axes[0, 0]
                ax.plot(conv_history['gen'], conv_history['best_rate'], 'o-',
                        color='#2980B9', linewidth=2, markersize=4, label='Best')
                ax.plot(conv_history['gen'], conv_history['avg_rate'], 's--',
                        color='#95A5A6', linewidth=1.5, markersize=3, label='Avg')
                ax.set_xlabel('Generation')
                ax.set_ylabel('Terminal Rate')
                ax.set_title('Terminal Rate Convergence')
                ax.legend(fontsize=8)
                ax.grid(alpha=0.3)
                
                # Build Cost
                ax = axes[0, 1]
                ax.plot(conv_history['gen'], conv_history['best_cost'], 'o-',
                        color='#8E44AD', linewidth=2, markersize=4)
                ax.set_xlabel('Generation')
                ax.set_ylabel('Build Cost')
                ax.set_title('Build Cost Convergence')
                ax.grid(alpha=0.3)
                
                # MHC
                ax = axes[1, 0]
                ax.plot(conv_history['gen'], conv_history['best_mhc'], 'o-',
                        color='#E67E22', linewidth=2, markersize=4)
                ax.set_xlabel('Generation')
                ax.set_ylabel('Material Handling Cost')
                ax.set_title('MHC Convergence')
                ax.grid(alpha=0.3)
                
                # Front diversity
                ax = axes[1, 1]
                ax.plot(conv_history['gen'], conv_history['front1'], 'o-',
                        color='#27AE60', linewidth=2, markersize=4, label='Front 1 size')
                ax.plot(conv_history['gen'], conv_history['distinct'], 's--',
                        color='#C0392B', linewidth=1.5, markersize=3, label='Distinct')
                ax.set_xlabel('Generation')
                ax.set_ylabel('Count')
                ax.set_title('Population Diversity')
                ax.legend(fontsize=8)
                ax.grid(alpha=0.3)
                
                plt.tight_layout()
                st.pyplot(fig)
                plt.close(fig)
                
                # Stats table
                st.subheader("Generation-by-Generation Stats")
                import pandas as pd
                gen_df = pd.DataFrame(conv_history)
                st.dataframe(gen_df, use_container_width=True)
                
            except Exception as e:
                st.error(f"❌ NSGA-II failed: {e}")
                import traceback
                st.code(traceback.format_exc())
        else:
            st.warning("run_nsga2() function not found in zpf_core. The engine may not be fully loaded.")

elif 'conv_history' in st.session_state:
    # Show cached results
    with tab2:
        st.header("NSGA-II Optimization (cached results)")
        conv_history = st.session_state['conv_history']
        
        fig, axes = plt.subplots(2, 2, figsize=(14, 10))
        fig.suptitle('NSGA-II Optimization Dashboard', fontsize=14, fontweight='bold')
        
        ax = axes[0, 0]
        ax.plot(conv_history['gen'], conv_history['best_rate'], 'o-',
                color='#2980B9', linewidth=2, markersize=4, label='Best')
        ax.plot(conv_history['gen'], conv_history['avg_rate'], 's--',
                color='#95A5A6', linewidth=1.5, markersize=3, label='Avg')
        ax.set_xlabel('Generation'); ax.set_ylabel('Terminal Rate')
        ax.set_title('Terminal Rate Convergence'); ax.legend(fontsize=8); ax.grid(alpha=0.3)
        
        ax = axes[0, 1]
        ax.plot(conv_history['gen'], conv_history['best_cost'], 'o-', color='#8E44AD', lw=2, ms=4)
        ax.set_xlabel('Generation'); ax.set_ylabel('Build Cost')
        ax.set_title('Build Cost Convergence'); ax.grid(alpha=0.3)
        
        ax = axes[1, 0]
        ax.plot(conv_history['gen'], conv_history['best_mhc'], 'o-', color='#E67E22', lw=2, ms=4)
        ax.set_xlabel('Generation'); ax.set_ylabel('MHC')
        ax.set_title('MHC Convergence'); ax.grid(alpha=0.3)
        
        ax = axes[1, 1]
        ax.plot(conv_history['gen'], conv_history['front1'], 'o-', color='#27AE60', lw=2, ms=4, label='Front 1')
        ax.plot(conv_history['gen'], conv_history['distinct'], 's--', color='#C0392B', lw=1.5, ms=3, label='Distinct')
        ax.set_xlabel('Generation'); ax.set_ylabel('Count')
        ax.set_title('Population Diversity'); ax.legend(fontsize=8); ax.grid(alpha=0.3)
        
        plt.tight_layout()
        st.pyplot(fig)
        plt.close(fig)

else:
    with tab2:
        st.header("NSGA-II Optimization")
        st.info("👈 Click **Run Pipeline** in the sidebar to start the optimization.")

# ── Tab 3: Layout Visualization (placeholder if no results) ──
with tab3:
    st.header("Layout Visualization")
    if 'final_pop' not in st.session_state:
        st.info("Run the pipeline first to see layout visualizations.")
    else:
        st.write("Layout visualization will appear here after Phase 2/3 completes.")

# ── Tab 4: ZPF Recovery ──
with tab4:
    st.header("ZPF Disaster Recovery")
    if 'final_pop' not in st.session_state:
        st.info("Run the pipeline first to see recovery results.")
    else:
        st.write("Recovery results will appear here after Phase 4 completes.")

# ── Tab 5: Simulation ──
with tab5:
    st.header("Discrete-Time Simulation")
    if 'final_pop' not in st.session_state:
        st.info("Run the pipeline first to see simulation results.")
    else:
        st.write("Simulation results will appear here after Phase 5 completes.")

# Footer
st.sidebar.markdown("---")
st.sidebar.markdown("**ZPF-DFLP** v6 • Vincentius Aditya")
st.sidebar.markdown("APU MSc AI Thesis 2026")
