from __future__ import annotations

import heapq
import math
import random
from collections import defaultdict, deque
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional

try:
    import matplotlib.pyplot as plt
    import matplotlib.patches as mpatches
    HAS_MPL = True
except ImportError:
    HAS_MPL = False
    print("[WARN] matplotlib not available — visualisation will be skipped.")

# Grid dimensions
GRID_W = 70
MIN_MACHINE_SPACING = 1  # Padding to spread machines

GRID_H = 70

# Time model
TICK_SECONDS    = 2.0  # (one tick = two seconds)
BELT_SPEED      = 1    # ticks per 1x1 belt cell
SIM_EQ_MAX_TICKS = 300  # maximum ticks to reach equilibrium
STARTUP_FREE    = True # during startup, power is not charged

# Battery power output table (from database 'machines prod' sheet)
BATTERY_POWER: dict[str, int] = {
    'power':      0,
    'LC_bat':   220,
    'SC_bat':   420,
    'HC_bat':  1100,
    'LC_W_bat': 1600,
    'SC_W_bat': 3200,
    'ori_ore':    50,
}

print(f"Grid          : {GRID_W}x{GRID_H}")
print(f"Belt speed    : {BELT_SPEED} tick/cell")



class Rotation(Enum):
    R0   = 0    # original orientation
    R90  = 90   # 90 deg clockwise
    R180 = 180  # 180 deg
    R270 = 270  # 270 deg clockwise


class TileState(Enum):
    EMPTY   = auto()
    MACHINE = auto()
    BELT    = auto()
    BLOCKED = auto()  # disruption zone (Phase 2)

print("Enums defined:", list(Rotation), list(TileState))

@dataclass
class Recipe:
    """One input -> output transformation a machine can perform."""
    inputs:       list[tuple[str, int]]  # [(material_name, qty), ...]
    outputs:      list[tuple[str, int]]  # [(material_name, qty), ...]
    process_time: int                    # ticks
    common_extra: list[tuple[str, int]] = field(default_factory=list)


@dataclass
class MachineType:
    """Blueprint for a machine type (not a placed instance)."""
    id:            str
    display_name:  str
    base_w:        int
    base_h:        int
    recipes:       list[Recipe]
    build_cost:    list[tuple[str, int]]
    power_cost:    int
    input_face_r0: str = "bottom"
    edge_only:     bool = False
    singleton:     bool = False
    is_power_src:  bool = False

    def size(self, rot: Rotation = Rotation.R0) -> tuple[int, int]:
        """Return (w, h) after rotation."""
        if rot in (Rotation.R0, Rotation.R180):
            return (self.base_w, self.base_h)
        return (self.base_h, self.base_w)

    def _rotate_face(self, face: str, rot: Rotation) -> str:
        """Rotate a face name by the given rotation (clockwise)."""
        order = ["top", "right", "bottom", "left"]
        steps = {Rotation.R0: 0, Rotation.R90: 1,
                 Rotation.R180: 2, Rotation.R270: 3}
        return order[(order.index(face) + steps[rot]) % 4]

    def io_faces(self, rot: Rotation = Rotation.R0) -> tuple[str, str]:
        """Return (input_face, output_face) after rotation."""
        if self.id == "main_unit":
            # main_unit has multi-face I/O; return comma-joined full face names
            in_faces = [self._rotate_face("left", rot), self._rotate_face("right", rot)]
            out_faces = [self._rotate_face("top", rot), self._rotate_face("bottom", rot)]
            return (",".join(in_faces), ",".join(out_faces))
        opposite = {"top": "bottom", "bottom": "top",
                    "left": "right",  "right": "left"}
        base_out = opposite[self.input_face_r0]
        in_face  = self._rotate_face(self.input_face_r0, rot)
        out_face = self._rotate_face(base_out, rot)
        return (in_face, out_face)

    def wider_face_len(self, rot: Rotation = Rotation.R0) -> int:
        """Number of cells on the wider (I/O) face after rotation."""
        w, h = self.size(rot)
        in_face, _ = self.io_faces(rot)
        if in_face in ('top', 'bottom'):
            return w
        return h



@dataclass
class PlacedMachine:
    """A machine placed on the grid."""
    machine_type:  MachineType
    x:             int
    y:             int
    rotation:      Rotation
    instance_id:   str = ""
    active_recipe: Optional[int] = None

    @property
    def w(self) -> int:
        return self.machine_type.size(self.rotation)[0]

    @property
    def h(self) -> int:
        return self.machine_type.size(self.rotation)[1]

    def cells(self) -> list[tuple[int, int]]:
        return [(self.x + dx, self.y + dy)
                for dy in range(self.h)
                for dx in range(self.w)]

    def _get_io_cells(self, face: str) -> list[tuple[int, int]]:
        """I/O node cells INSIDE the machine on the given face."""
        w, h = self.w, self.h
        if face == "top":    return [(self.x + dx, self.y)           for dx in range(w)]
        if face == "bottom": return [(self.x + dx, self.y + h - 1)  for dx in range(w)]
        if face == "left":   return [(self.x,       self.y + dy)     for dy in range(h)]
        if face == "right":  return [(self.x + w - 1, self.y + dy)  for dy in range(h)]
        raise ValueError(f"Unknown face: {face}")

    def _get_main_unit_io_nodes(self, face: str) -> list[tuple[int, int]]:
        w, h = self.w, self.h
        if face == "top":    return [(self.x + dx, self.y)           for dx in (1, 4, 7)]
        if face == "bottom": return [(self.x + dx, self.y + h - 1)  for dx in (1, 4, 7)]
        if face == "left":   return [(self.x,       self.y + dy)     for dy in range(1, 8)]
        if face == "right":  return [(self.x + w - 1, self.y + dy)  for dy in range(1, 8)]
        return []

    def input_nodes(self)  -> list[tuple[int, int]]:
        if self.machine_type.id == "main_unit":
            faces = [self.machine_type._rotate_face("left", self.rotation),
                     self.machine_type._rotate_face("right", self.rotation)]
            return [n for f in faces for n in self._get_main_unit_io_nodes(f)]
        in_face, _ = self.machine_type.io_faces(self.rotation)
        return self._get_io_cells(in_face)

    def output_nodes(self) -> list[tuple[int, int]]:
        if self.machine_type.id == "main_unit":
            faces = [self.machine_type._rotate_face("top", self.rotation),
                     self.machine_type._rotate_face("bottom", self.rotation)]
            return [n for f in faces for n in self._get_main_unit_io_nodes(f)]
        _, out_face = self.machine_type.io_faces(self.rotation)
        return self._get_io_cells(out_face)

    def input_node_centre(self)  -> tuple[int, int]:
        nodes = self.input_nodes();  return nodes[len(nodes) // 2]

    def output_node_centre(self) -> tuple[int, int]:
        nodes = self.output_nodes(); return nodes[len(nodes) // 2]

    def _get_belt_connect_cells(self, face: str) -> list[tuple[int, int]]:
        """Cells OUTSIDE the machine, adjacent to the given face."""
        w, h = self.w, self.h
        if face == "top":    return [(self.x + dx, self.y - 1)  for dx in range(w)]
        if face == "bottom": return [(self.x + dx, self.y + h)  for dx in range(w)]
        if face == "left":   return [(self.x - 1,  self.y + dy) for dy in range(h)]
        if face == "right":  return [(self.x + w,  self.y + dy) for dy in range(h)]
        raise ValueError(f"Unknown face: {face}")

    def _get_main_unit_points(self, face: str) -> list[tuple[int, int]]:
        w, h = self.w, self.h
        if face == "top":    return [(self.x + dx, self.y - 1)  for dx in (1, 4, 7)]
        if face == "bottom": return [(self.x + dx, self.y + h)  for dx in (1, 4, 7)]
        if face == "left":   return [(self.x - 1,  self.y + dy) for dy in range(1, 8)]
        if face == "right":  return [(self.x + w,  self.y + dy) for dy in range(1, 8)]
        return []

    def input_belt_points(self)  -> list[tuple[int, int]]:
        if self.machine_type.id == "main_unit":
            faces = [self.machine_type._rotate_face("left", self.rotation),
                     self.machine_type._rotate_face("right", self.rotation)]
            return [n for f in faces for n in self._get_main_unit_points(f)]
        in_face, _ = self.machine_type.io_faces(self.rotation)
        return self._get_belt_connect_cells(in_face)

    def output_belt_points(self) -> list[tuple[int, int]]:
        if self.machine_type.id == "main_unit":
            faces = [self.machine_type._rotate_face("top", self.rotation),
                     self.machine_type._rotate_face("bottom", self.rotation)]
            return [n for f in faces for n in self._get_main_unit_points(f)]
        _, out_face = self.machine_type.io_faces(self.rotation)
        return self._get_belt_connect_cells(out_face)


    def input_belt_centre(self)  -> tuple[int, int]:
        pts = self.input_belt_points();  return pts[len(pts) // 2]

    def output_belt_centre(self) -> tuple[int, int]:
        pts = self.output_belt_points(); return pts[len(pts) // 2]


@dataclass
class FlowPair:
    """Directed material flow between two machine instances."""
    src_id:       str
    dst_id:       str
    material:     str
    intensity:    float
    src_node_idx: int = 0   # which output node on the source machine
    dst_node_idx: int = 0   # which input node slot on the destination machine

print("Data classes defined: Recipe, MachineType, PlacedMachine, FlowPair")



def _build_machine_catalogue() -> dict[str, MachineType]:
    machines = {}

    machines["refining_unit"] = MachineType(
        id="refining_unit", display_name="Refining Unit",
        base_w=3, base_h=3, input_face_r0="bottom",
        recipes=[
            Recipe([("ori_ore", 1)],             [("ori_crust", 1)],            2),
            Recipe([("ame_ore", 1)],             [("ame_fiber", 1)],            2),
            Recipe([("ferri_ore", 1)],           [("ferrium", 1)],              2),
            Recipe([("citrome", 1)],             [("carbon", 1)],               2),
            Recipe([("sandleaf", 1)],            [("carbon", 1)],               2),
            Recipe([("buckflower", 1)],          [("carbon", 1)],               2),
            Recipe([("dense_ori_pow", 1)],       [("dense_ori_crust_pow", 1)],  2),
            Recipe([("cryston_pow", 1)],         [("cryston_fiber", 1)],        2),
            Recipe([("dense_carbon_pow", 1)],    [("stabilized_carbon", 1)],    2),
            Recipe([("dense_ori_crust_pow", 1)], [("packed_origo_crust", 1)],   2),
            Recipe([("dense_ferri_pow", 1)],     [("steel", 1)],                2),
            Recipe([("sandleaf_pow", 3)],        [("carbon_pow", 2)],           2),
            Recipe([("ori_pow", 1)],             [("ori_crust_pow", 1)],        2),
        ],
        build_cost=[("ori_ore", 5)], power_cost=10,
    )

    machines["shredding_unit"] = MachineType(
        id="shredding_unit", display_name="Shredding Unit",
        base_w=3, base_h=3, input_face_r0="bottom",
        recipes=[
            Recipe([("ori_ore", 1)],    [("ori_pow", 1)],       2),
            Recipe([("ferrium", 1)],    [("ferri_pow", 1)],     2),
            Recipe([("ame_fiber", 1)],  [("ame_pow", 1)],       2),
            Recipe([("carbon", 1)],     [("carbon_pow", 2)],    2),
            Recipe([("ori_crust", 1)],  [("ori_crust_pow", 1)], 2),
            Recipe([("buckflower", 1)], [("buck_pow", 2)],      2),
            Recipe([("citrome", 1)],    [("citrome_pow", 2)],   2),
            Recipe([("sandleaf", 1)],   [("sandleaf_pow", 2)],  2),
            Recipe([("aketine", 1)],    [("ake_pow", 2)],       2),
        ],
        build_cost=[("ori_crust", 5)], power_cost=10,
    )

    machines["fitting_unit"] = MachineType(
        id="fitting_unit", display_name="Fitting Unit",
        base_w=3, base_h=3, input_face_r0="bottom",
        recipes=[
            Recipe([("steel", 1)],         [("steel_part", 1)],   2),
            Recipe([("ferrium", 1)],       [("ferri_part", 1)],   2),
            Recipe([("cryston_fiber", 1)], [("cryston_part", 1)], 2),
            Recipe([("ame_fiber", 1)],     [("ame_part", 1)],     2),
        ],
        build_cost=[("ori_crust", 10)], power_cost=10,
    )

    machines["moulding_unit"] = MachineType(
        id="moulding_unit", display_name="Moulding Unit",
        base_w=3, base_h=3, input_face_r0="bottom",
        recipes=[
            Recipe([("steel", 2)],         [("steel_bottle", 1)],    2),
            Recipe([("ferrium", 2)],       [("ferrium_bottle", 1)],  2),
            Recipe([("ame_fiber", 2)],     [("ame_bottle", 1)],      2),
            Recipe([("cryston_fiber", 2)], [("cryston_bottle", 1)],  2),
        ],
        build_cost=[("ori_crust", 10)], power_cost=10,
    )

    machines["grinding_unit"] = MachineType(
        id="grinding_unit", display_name="Grinding Unit",
        base_w=6, base_h=4, input_face_r0="top",
        recipes=[
            Recipe([("buck_pow", 2)],      [("ground_buck_pow", 1)],     2, common_extra=[("sandleaf_pow", 1)]),
            Recipe([("ori_pow", 2)],       [("dense_ori_pow", 1)],       2),
            Recipe([("ame_pow", 2)],       [("cryston_pow", 1)],         2),
            Recipe([("ferri_pow", 2)],     [("dense_ferri_pow", 1)],     2),
            Recipe([("carbon_pow", 2)],    [("dense_carbon_pow", 1)],    2),
            Recipe([("citrome_pow", 2)],   [("ground_citrome_pow", 1)],  2),
            Recipe([("ori_crust_pow", 2)], [("dense_ori_crust_pow", 1)], 2),
        ],
        build_cost=[("ferri_part", 10)], power_cost=20,
    )

    machines["filling_unit"] = MachineType(
        id="filling_unit", display_name="Filling Unit",
        base_w=6, base_h=4, input_face_r0="top",
        recipes=[
            Recipe([("steel_bottle", 10),   ("ground_buck_pow", 10)],   [("buck_cap_A", 1)], 10),
            Recipe([("steel_bottle", 10),   ("ground_citrome_pow", 10)], [("can_cit_A", 1)], 10),
            Recipe([("ferrium_bottle", 10), ("ground_buck_pow", 10)],   [("buck_cap_B", 1)], 10),
            Recipe([("ferrium_bottle", 10), ("ground_citrome_pow", 10)], [("can_cit_B", 1)], 10),
            Recipe([("ame_bottle", 10),     ("ground_buck_pow", 10)],   [("buck_cap_C", 1)], 10),
            Recipe([("ame_bottle", 10),     ("ground_citrome_pow", 10)], [("can_cit_C", 1)], 10),
        ],
        build_cost=[("ame_part", 20)], power_cost=20,
    )

    machines["packaging_unit"] = MachineType(
        id="packaging_unit", display_name="Packaging Unit",
        base_w=6, base_h=4, input_face_r0="top",
        recipes=[
            Recipe([("steel_part", 10), ("dense_ori_pow", 15)],  [("HC_bat", 1)], 10),
            Recipe([("ame_part", 5),    ("ori_pow", 10)],        [("LC_bat", 1)], 10),
            Recipe([("ferri_part", 10), ("ori_pow", 15)],        [("SC_bat", 1)], 10),
        ],
        build_cost=[("ame_part", 20)], power_cost=20,
    )

    machines["planting_unit"] = MachineType(
        id="planting_unit", display_name="Planting Unit",
        base_w=5, base_h=5, input_face_r0="top",
        recipes=[Recipe([(f"{p}_seed", 1)], [(p, 2)], 1) for p in ["citrome", "sandleaf", "buckflower", "aketine"]],
        build_cost=[("ame_part", 20), ("carbon", 10)], power_cost=30,
    )

    machines["seed_picking_unit"] = MachineType(
        id="seed_picking_unit", display_name="Seed-Picking Unit",
        base_w=5, base_h=5, input_face_r0="bottom",
        recipes=[Recipe([(p, 1)], [(f"{p}_seed", 2)], 1) for p in ["citrome", "sandleaf", "buckflower", "aketine"]],
        build_cost=[("ame_part", 20)], power_cost=30,
    )

    machines["ther_bank"] = MachineType(
        id="ther_bank", display_name="Thermal Bank",
        base_w=2, base_h=2, input_face_r0="top",
        recipes=[
            Recipe([("ori_ore", 1)],  [("power", 50)],   8),
            Recipe([("LC_bat", 1)],   [("power", 220)],  100),
            Recipe([("HC_bat", 1)],   [("power", 1100)], 100),
            Recipe([("SC_bat", 1)],   [("power", 420)],  100),
            Recipe([("LC_W_bat", 1)], [("power", 1600)], 100),
            Recipe([("SC_W_bat", 1)], [("power", 3200)], 100),
        ],
        build_cost=[("ori_crust", 10), ("ame_part", 10)],
        power_cost=0, is_power_src=True,
    )

    machines["stash"] = MachineType(
        id="stash", display_name="Stash",
        base_w=3, base_h=3, input_face_r0="bottom",
        recipes=[], build_cost=[], power_cost=10,
    )

    machines["depot_loader"] = MachineType(
        id="depot_loader", display_name="Depot Loader",
        base_w=3, base_h=1, input_face_r0="top",
        recipes=[], build_cost=[], power_cost=0, edge_only=True,
    )

    machines["depot_unloader"] = MachineType(
        id="depot_unloader", display_name="Depot Unloader",
        base_w=3, base_h=1, input_face_r0="bottom",
        recipes=[], build_cost=[], power_cost=0, edge_only=True,
    )

    machines["main_unit"] = MachineType(
        id="main_unit", display_name="Main Unit",
        base_w=9, base_h=9, input_face_r0="bottom",
        recipes=[], build_cost=[], power_cost=0, singleton=True,
    )

    return machines


MACHINE_CATALOGUE = _build_machine_catalogue()

REVENUE_TABLE: dict[str, int] = {
    "buck_cap_A": 70, "can_cit_A": 70,
    "buck_cap_B": 27, "can_cit_B": 27,
    "buck_cap_C": 10, "can_cit_C": 10,
    "HC_bat": 27, "SC_bat": 30, "LC_bat": 16,
    "ori_crust": 1, "ame_bottle": 2,
    "ame_part": 1, "ferri_part": 1, "steel_part": 3,
}

print(f"Machine types registered: {len(MACHINE_CATALOGUE)}")
print(f"Revenue items tracked   : {len(REVENUE_TABLE)}")

# Quick catalogue summary
print("\n--- Machine Catalogue ---")
for mid, mt in MACHINE_CATALOGUE.items():
    extra = []
    if mt.edge_only:    extra.append("EDGE-ONLY")
    if mt.singleton:    extra.append("SINGLETON")
    if mt.is_power_src: extra.append("POWER-SRC")
    tags   = f" [{', '.join(extra)}]" if extra else ""
    in_f, out_f = mt.io_faces(Rotation.R0)
    print(f"  {mt.display_name:25s}  {mt.base_w}x{mt.base_h}  "
          f"power={mt.power_cost:3d}  in={in_f:6s} out={out_f:6s}  "
          f"recipes={len(mt.recipes)}{tags}")






def derive_flow_matrix(
    placed_machines: list[PlacedMachine],
) -> list[FlowPair]:
    """Build flow pairs with fractional demand and multi-port tracking.
    
    Rules:
    - Tracks exactly how much decimal demand each consumer has.
    - Multiple suppliers can route to one consumer.
    - One supplier can route to multiple consumers.
    - Each 1.0 item/sec routed consumes ONE physical output port on the supplier 
      and ONE physical input port on the consumer.
    - 'seed_picking_unit' outputs 2 items, which natively gets translated to 
      2 distinct belts if it's fed to consumers, because the while loop runs twice.
    """
    flows: list[FlowPair] = []

    used_out_nodes: dict[str, int] = defaultdict(int)
    used_in_nodes:  dict[str, int] = defaultdict(int)

    supply: dict[str, list[tuple[str, float]]] = defaultdict(list)
    demand: dict[str, list[tuple[str, float, int]]] = defaultdict(list)

    for pm in placed_machines:
        if pm.active_recipe is None or not pm.machine_type.recipes:
            continue
        if pm.active_recipe >= len(pm.machine_type.recipes):
            continue
        recipe = pm.machine_type.recipes[pm.active_recipe]
        for mat, qty in recipe.outputs:
            supply[mat].append((pm.instance_id, float(qty)))
        for ing_pos, (mat, qty) in enumerate(recipe.inputs):
            demand[mat].append((pm.instance_id, float(qty), ing_pos))
        for mat, qty in recipe.common_extra:
            demand[mat].append((pm.instance_id, float(qty), len(recipe.inputs)))

    # V5 CONTINUITY FIX: The Hub as Source and Sink
    hub_suppliers = [p.instance_id for p in placed_machines if p.machine_type.id in ('main_unit', 'depot_loader', 'depot_unloader')]
    if hub_suppliers:
        hub_id = hub_suppliers[0] # Usually main_unit_0 or similar
        
        # 1. Source Continuity (Raw Materials): If a material is demanded but has NO active producers,
        # it MUST come from the global inventory (Main Unit). This forces the A* router to draw a belt!
        for mat, cons in list(demand.items()):
            if mat not in supply or not supply[mat]:
                total_dem = sum(qty for _, qty, _ in cons)
                supply[mat].append((hub_id, total_dem))
                
        # 2. Sink Continuity (Revenue Products): If a material is a revenue target, it MUST be stashed
        # into the global inventory (Main Unit). This guarantees output belts are drawn for everything!
        for mat in TARGET_PRODUCTS:
            if mat in supply:
                tot_supply = sum(qty for _, qty in supply[mat])
                tot_demand = sum(qty for _, qty, _ in demand.get(mat, []))
                surplus = tot_supply - tot_demand
                if surplus > 1e-9:
                    demand[mat].append((hub_id, surplus, -1))

    # V5 WEB ROUTING: Formalize Inventory Sources & Sinks
    inventory_sinks = [p.instance_id for p in placed_machines if p.machine_type.id in ('main_unit', 'stash', 'depot_loader')]
    inventory_sources = [p.instance_id for p in placed_machines if p.machine_type.id in ('main_unit', 'depot_unloader')]
    
    # 1. Source Continuity (Raw Materials FROM inventory)
    if inventory_sources:
        source_id = inventory_sources[0]
        for mat, cons in list(demand.items()):
            if mat not in supply or not supply[mat]:
                total_dem = sum(qty for _, qty, _ in cons)
                if mat not in supply: supply[mat] = []
                supply[mat].append((source_id, total_dem))
                
    # 2. Sink Continuity (Revenue Products INTO inventory)
    if inventory_sinks:
        sink_id = inventory_sinks[0]
        for mat in TARGET_PRODUCTS:
            if mat in supply:
                tot_supply = sum(qty for _, qty in supply[mat])
                tot_demand = sum(qty for _, qty, _ in demand.get(mat, []))
                surplus = tot_supply - tot_demand
                if surplus > 1e-9:
                    if mat not in demand: demand[mat] = []
                    demand[mat].append((sink_id, surplus, -1))

    unfulfilled_demand = {}
    for mat, cons in demand.items():
        for con_id, con_qty, ing_pos in cons:
            unfulfilled_demand[(mat, con_id)] = con_qty

    # --- Matchmaking ---
    for material, suppliers in supply.items():
        consumers = demand.get(material, [])
        for sup_id, sup_qty in suppliers:
            src_pm = next((p for p in placed_machines if p.instance_id == sup_id), None)
            
            while sup_qty > 1e-9:
                best_con = None
                for con_id, con_qty, ing_pos in consumers:
                    if sup_id == con_id:
                        continue
                    rem = unfulfilled_demand.get((material, con_id), 0.0)
                    if rem > 1e-9:
                        best_con = (con_id, con_qty, ing_pos, rem)
                        break
                
                if not best_con:
                    break
                
                con_id, con_qty, ing_pos, rem = best_con
                dst_pm = next((p for p in placed_machines if p.instance_id == con_id), None)
                
                out_nodes = src_pm.output_belt_points() if src_pm else []
                src_node  = used_out_nodes[sup_id] % max(1, len(out_nodes))
                used_out_nodes[sup_id] += 1
                
                in_nodes  = dst_pm.input_belt_points() if dst_pm else []
                dst_node  = used_in_nodes[con_id] % max(1, len(in_nodes))
                used_in_nodes[con_id] += 1
                
                transfer = min(1.0, sup_qty, rem)
                
                flows.append(FlowPair(
                    src_id=sup_id,
                    dst_id=con_id,
                    material=material,
                    intensity=float(transfer),
                    src_node_idx=src_node,
                    dst_node_idx=dst_node,
                ))
                
                sup_qty -= transfer
                unfulfilled_demand[(material, con_id)] -= transfer

    # NOTE: packaging_unit -> ther_bank battery flows are already created by the
    # general supply/demand matching loop above (ther_bank's own recipe.inputs
    # declares its battery requirement). This special-case used to duplicate
    # that same edge for every placed packaging_unit, always targeting the
    # first ther_bank found -- inflating flows_total with duplicate FlowPairs.

    # Find physical sinks on the map
    sinks = [p for p in placed_machines if p.machine_type.id in ('main_unit', 'stash', 'depot_loader')]

    # Revenue items -> Nearest physical sink
    # Allow machines to sell their surplus! If a machine has 3 output ports,
    # it can use 1 port for a consumer, and 2 ports to route surplus to the stash!
    for pm in placed_machines:
        if pm.active_recipe is not None and pm.machine_type.recipes:
            if pm.active_recipe < len(pm.machine_type.recipes):
                recipe = pm.machine_type.recipes[pm.active_recipe]
                for mat, qty in recipe.outputs:
                    if mat in REVENUE_TABLE:
                        sent = sum(fp.intensity for fp in flows if fp.src_id == pm.instance_id and fp.material == mat)
                        surplus = qty - sent
                        
                        while surplus > 1e-9:
                            out_nodes = pm.output_belt_points()
                            src_node  = used_out_nodes[pm.instance_id] % max(1, len(out_nodes))
                            used_out_nodes[pm.instance_id] += 1
                            
                            transfer = min(1.0, surplus)
                            
                            # Give A* a real physical machine to target!
                            if not sinks:
                                break  # No physical sink — skip this flow entirely
                            # Find the physically closest sink using Manhattan distance
                            best_sink = min(sinks, key=lambda s: abs(s.x - pm.x) + abs(s.y - pm.y))
                            dst_id = best_sink.instance_id
                            
                            flows.append(FlowPair(
                                src_id=pm.instance_id,
                                dst_id=dst_id,
                                material=mat,
                                intensity=float(transfer),
                                src_node_idx=src_node,
                                dst_node_idx=0,
                            ))
                            surplus -= transfer

    # main_unit -> depot_loader
    main_units    = [pm for pm in placed_machines if pm.machine_type.id == 'main_unit']
    depot_loaders = [pm for pm in placed_machines if pm.machine_type.id == 'depot_loader']
    if main_units and depot_loaders:
        flows.append(FlowPair(
            src_id=main_units[0].instance_id,
            dst_id=depot_loaders[0].instance_id,
            material="items_to_depot",
            intensity=4.0,
            src_node_idx=0,
            dst_node_idx=0,
        ))

    return flows
class FactoryGrid:
    """50x50 discrete grid — machine footprints and belt cells are mutually exclusive."""

    def __init__(self, width: int = GRID_W, height: int = GRID_H):
        self.width   = width
        self.height  = height
        self.grid: list[list[tuple[TileState, Optional[str]]]] = [
            [(TileState.EMPTY, None) for _ in range(width)]
            for _ in range(height)
        ]
        self.placed_machines: list[PlacedMachine] = []
        self.belt_paths: list[tuple[str, list[tuple[int, int]]]] = []

    def in_bounds(self, x: int, y: int) -> bool:
        return 0 <= x < self.width and 0 <= y < self.height

    def is_free(self, x: int, y: int) -> bool:
        return self.in_bounds(x, y) and self.grid[y][x][0] == TileState.EMPTY

    def is_routable(self, x: int, y: int) -> bool:
        return self.in_bounds(x, y) and self.grid[y][x][0] in (TileState.EMPTY, TileState.BELT)

    def can_place(self, x: int, y: int, w: int, h: int) -> bool:
        if x < 0 or y < 0 or x + w > self.width or y + h > self.height:
            return False
        return all(self.is_free(x + dx, y + dy)
                   for dy in range(h) for dx in range(w))

    def is_on_edge(self, x: int, y: int, w: int, h: int) -> bool:
        if w > h:   return y == 0 or y + h == self.height
        elif h > w: return x == 0 or x + w == self.width
        return x == 0 or y == 0 or x + w == self.width or y + h == self.height


    def check_clearance(self, x: int, y: int, w: int, h: int, clearance: int) -> bool:
        """Check if an area, expanded by clearance, is free of other machines.
        Clearance cells that fall outside the grid bounds are ignored."""
        if x < 0 or y < 0 or x + w > self.width or y + h > self.height:
            return False

        cx_start = max(0, x - clearance)
        cy_start = max(0, y - clearance)
        cx_end   = min(self.width, x + w + clearance)
        cy_end   = min(self.height, y + h + clearance)

        for cy in range(cy_start, cy_end):
            for cx in range(cx_start, cx_end):
                if self.grid[cy][cx][0] != TileState.EMPTY:
                    return False
        return True

    def place_machine(self, pm: PlacedMachine) -> bool:
        # Must return True on success -- an implicit `return None` here is
        # falsy just like False, and zpf_recovery()'s recover() closure
        # branches on this return value (`if grid.place_machine(pm):
        # placed.append(pm)`), so recovery never placed a single machine
        # back, not even untouched "stable" ones.
        w, h = pm.w, pm.h
        if not self.can_place(pm.x, pm.y, w, h):
            return False
        if pm.machine_type.edge_only and not self.is_on_edge(pm.x, pm.y, w, h):
            return False
        for (cx, cy) in pm.cells():
            self.grid[cy][cx] = (TileState.MACHINE, pm.machine_type.id)
        self.placed_machines.append(pm)
        return True

    def remove_machine(self, pm: PlacedMachine):
        """Remove a machine from the grid (TileState) and the placed_machines list."""
        for dy in range(pm.h):
            for dx in range(pm.w):
                if self.grid[pm.y + dy][pm.x + dx][1] == pm.instance_id:
                    self.grid[pm.y + dy][pm.x + dx] = (TileState.EMPTY, None)
        if pm in self.placed_machines:
            self.placed_machines.remove(pm)
        return True

    def place_belt(self, path: list[tuple[int, int]], label: str = "belt") -> bool:
        """Place belt, allowing perpendicular intersections."""
        if any(not self.in_bounds(x, y) or not self.is_routable(x, y) for x, y in path):
            return False

        for i, (x, y) in enumerate(path):
            axes = set()
            if i > 0:
                dx, dy = abs(x - path[i-1][0]), abs(y - path[i-1][1])
                if dx > 0: axes.add('H')
                if dy > 0: axes.add('V')
            if i < len(path) - 1:
                dx, dy = abs(path[i+1][0] - x), abs(path[i+1][1] - y)
                if dx > 0: axes.add('H')
                if dy > 0: axes.add('V')

            if self.grid[y][x][0] == TileState.EMPTY:
                self.grid[y][x] = (TileState.BELT, axes)
            elif self.grid[y][x][0] == TileState.BELT:
                existing = self.grid[y][x][1]
                if not isinstance(existing, set):
                    existing = set()
                self.grid[y][x] = (TileState.BELT, existing.union(axes))

        self.belt_paths.append((label, list(path)))
        return True


    def render(self) -> str:
        sym_map = {TileState.EMPTY: ".", TileState.MACHINE: "#",
                   TileState.BELT: "~",  TileState.BLOCKED: "X"}
        hdr   = "   " + "".join(f"{c % 10}" for c in range(self.width))
        lines = [hdr]
        for y in range(self.height):
            row = [sym_map.get(self.grid[y][x][0], "?") for x in range(self.width)]
            lines.append(f"{y:2d} {''.join(row)}")
        return "\n".join(lines)

print("FactoryGrid defined.")


@dataclass
class Gene:
    machine_id: str
    rotation:   Rotation
    recipe_idx: Optional[int] = None
@dataclass
class Chromosome:
    genes: list[Gene]
    @staticmethod
    def random(
        machine_ids: list[str],
        recipe_assignments: Optional[list[Optional[int]]] = None,
    ) -> "Chromosome":
        """Create a random chromosome with shuffled gene order."""
        genes = []
        for i, mid in enumerate(machine_ids):
            rot  = random.choice(list(Rotation))
            ridx = (recipe_assignments[i] if recipe_assignments is not None
                    else (0 if MACHINE_CATALOGUE[mid].recipes else None))
            genes.append(Gene(mid, rot, ridx))
        random.shuffle(genes)
        return Chromosome(genes)
    def copy(self) -> "Chromosome":
        return Chromosome([Gene(g.machine_id, g.rotation, g.recipe_idx)
                           for g in self.genes])
print("Gene and Chromosome defined.")

BLF_VERBOSE = False
BLF_UNPLACED_COUNT = 0

def derive_topology(chromosome):
    """Run a mock flow match to get topological neighbors before placement."""
    mock_placed = []
    instance_counters = defaultdict(int)
    for gene in chromosome.genes:
        idx = instance_counters[gene.machine_id]
        instance_counters[gene.machine_id] += 1
        inst_id = f"{gene.machine_id}_{idx}"
        mtype = MACHINE_CATALOGUE[gene.machine_id]
        pm = PlacedMachine(machine_type=mtype, x=0, y=0, rotation=gene.rotation,
                           instance_id=inst_id, active_recipe=gene.recipe_idx)
        mock_placed.append(pm)

    flows = derive_flow_matrix(mock_placed)
    neighbors = defaultdict(set)
    for f in flows:
        neighbors[f.src_id].add(f.dst_id)
        neighbors[f.dst_id].add(f.src_id)
    return neighbors

def generate_spiral(cx, cy, max_r):
    """Yields (x, y) coordinates radiating outward from cx, cy."""
    yield cx, cy
    for r in range(1, max_r + 1):
        for x in range(cx - r, cx + r): yield x, cy - r
        for y in range(cy - r, cy + r): yield cx + r, y
        for x in range(cx + r, cx - r, -1): yield x, cy + r
        for y in range(cy + r, cy - r, -1): yield cx - r, y

def blf_decode(chromosome: Chromosome, grid: FactoryGrid) -> list[PlacedMachine]:
    """BLF decode with port-in-bounds validation and Adjacency-Biased Spiral Search."""
    global BLF_UNPLACED_COUNT
    placed: list[PlacedMachine] = []
    instance_counters: dict[str, int] = defaultdict(int)

    topology = derive_topology(chromosome)
    placed_by_id = {}

    for gene in chromosome.genes:
        mtype = MACHINE_CATALOGUE[gene.machine_id]
        w, h  = mtype.size(gene.rotation)

        idx     = instance_counters[gene.machine_id]
        instance_counters[gene.machine_id] += 1
        inst_id = f"{gene.machine_id}_{idx}"

        y_start, x_start = (0, 0) if mtype.edge_only else (1, 1)
        y_end   = grid.height - h + 1
        x_end   = grid.width  - w + 1

        search_sequence = []
        placed_neighbors = [placed_by_id[nid] for nid in topology[inst_id] if nid in placed_by_id]
        if placed_neighbors and not mtype.edge_only:
            cx = int(sum(p.x + p.w/2 for p in placed_neighbors) / len(placed_neighbors))
            cy = int(sum(p.y + p.h/2 for p in placed_neighbors) / len(placed_neighbors))
            cx, cy = int(cx - w/2), int(cy - h/2)

            for nx, ny in generate_spiral(cx, cy, 25):
                if x_start <= nx < x_end and y_start <= ny < y_end:
                    search_sequence.append((nx, ny))

        if placed_neighbors and not mtype.edge_only:
            # Distance-sorted fallback: closest to supply-chain centroid first
            fallback_sequence = sorted(
                ((x, y) for y in range(y_start, y_end) for x in range(x_start, x_end)),
                key=lambda p: abs(p[0] - cx) + abs(p[1] - cy)
            )
        else:
            # No neighbors yet — standard BLF bottom-left scan
            fallback_sequence = [(x, y) for y in range(y_start, y_end)
                                 for x in range(x_start, x_end)]
        search_sequence.extend(fallback_sequence)

        seen = set()
        unique_search = []
        for nx, ny in search_sequence:
            if (nx, ny) not in seen:
                seen.add((nx, ny))
                unique_search.append((nx, ny))

        success = False
        for clearance_val in [MIN_MACHINE_SPACING]:
            if success:
                break
            for x, y in unique_search:
                if mtype.edge_only and not grid.is_on_edge(x, y, w, h):
                    continue
                if not grid.check_clearance(x, y, w, h, clearance=clearance_val):
                    continue
                pm = PlacedMachine(machine_type=mtype, x=x, y=y,
                                   rotation=gene.rotation,
                                   instance_id=inst_id,
                                   active_recipe=gene.recipe_idx)
                if not mtype.edge_only:
                    ports_ok = all(grid.in_bounds(px, py)
                                   for px, py in
                                   pm.input_belt_points() + pm.output_belt_points())
                    if not ports_ok:
                        continue
                grid.place_machine(pm)
                placed.append(pm)
                placed_by_id[inst_id] = pm
                success = True
                break

        if not success:
            BLF_UNPLACED_COUNT += 1
            if BLF_VERBOSE:
                print(f"  [BLF] WARNING: Could not place {mtype.display_name} ({w}x{h})")

    return placed

print("blf_decode() defined with Smarter Adjacency-Biased Spiral Search.")



def astar(
    grid:  FactoryGrid,
    start: tuple[int, int],
    goal:  tuple[int, int],
) -> Optional[list[tuple[int, int]]]:
    """A* on EMPTY cells — cardinal moves only."""
    sx, sy = start
    gx, gy = goal
    if (not grid.in_bounds(sx, sy) or not grid.in_bounds(gx, gy)
            or not grid.is_routable(sx, sy) or not grid.is_routable(gx, gy)):
        return None

    h       = lambda x, y: abs(x - gx) + abs(y - gy)
    counter = 0
    open_set: list[tuple[int, int, int, int]] = []
    heapq.heappush(open_set, (h(sx, sy), counter, sx, sy))
    g_score:   dict[tuple[int, int], int]                 = {(sx, sy): 0}
    came_from: dict[tuple[int, int], tuple[int, int]]     = {}
    closed:    set[tuple[int, int]]                        = set()
    DIRS = [(0, 1), (0, -1), (1, 0), (-1, 0)]

    while open_set:
        _, _, cx, cy = heapq.heappop(open_set)
        if (cx, cy) == (gx, gy):
            path = [(gx, gy)]
            node = (gx, gy)
            while node in came_from:
                node = came_from[node]
                path.append(node)
            path.reverse()
            return path
        if (cx, cy) in closed:
            continue
        closed.add((cx, cy))
        for dx, dy in DIRS:
            nx, ny = cx + dx, cy + dy
            if not grid.in_bounds(nx, ny) or (nx, ny) in closed:
                continue
            if not grid.is_routable(nx, ny):
                continue

            # --- NEW INTERSECTION LOGIC ---
            # Check exit from cx, cy
            if grid.grid[cy][cx][0] == TileState.BELT:
                axes = grid.grid[cy][cx][1]
                if not isinstance(axes, set): axes = set()
                if 'H' in axes and 'V' in axes:
                    continue
                if 'H' in axes and dx != 0:
                    continue
                if 'V' in axes and dy != 0:
                    continue

            # Check enter to nx, ny
            if grid.grid[ny][nx][0] == TileState.BELT:
                axes = grid.grid[ny][nx][1]
                if not isinstance(axes, set): axes = set()
                if 'H' in axes and 'V' in axes:
                    continue
                if 'H' in axes and dx != 0:
                    continue
                if 'V' in axes and dy != 0:
                    continue
            # ------------------------------

            tg = g_score[(cx, cy)] + 1
            if tg < g_score.get((nx, ny), float('inf')):
                g_score[(nx, ny)] = tg
                came_from[(nx, ny)] = (cx, cy)
                counter += 1
                heapq.heappush(open_set, (tg + h(nx, ny), counter, nx, ny))
    return None


def route_belts(
    grid:          FactoryGrid,
    placed_lookup: dict[str, PlacedMachine],
    flow_matrix:   list[FlowPair],
) -> list[tuple[FlowPair, Optional[list[tuple[int, int]]]]]:
    """Route each FlowPair using its specific assigned src/dst node indices.

    Flows are sorted in TOPOLOGICAL ORDER (upstream first) so that critical
    supply-chain connections get first priority on grid space. Downstream
    and surplus belts are routed last.
    """
    # ── Topological sort of flows ──
    # Build a DAG of machine instance IDs from the flow pairs
    from collections import defaultdict, deque
    outgoing = defaultdict(set)
    indeg = defaultdict(int)
    all_ids = set()
    for fp in flow_matrix:
        all_ids.add(fp.src_id)
        all_ids.add(fp.dst_id)
    for nid in all_ids:
        indeg.setdefault(nid, 0)
    for fp in flow_matrix:
        if fp.dst_id not in outgoing[fp.src_id]:
            outgoing[fp.src_id].add(fp.dst_id)
            indeg[fp.dst_id] += 1

    # Kahn's algorithm
    q = deque(nid for nid in all_ids if indeg[nid] == 0)
    topo_order = {}
    rank = 0
    while q:
        node = q.popleft()
        topo_order[node] = rank
        rank += 1
        for dst in outgoing[node]:
            indeg[dst] -= 1
            if indeg[dst] == 0:
                q.append(dst)
    # Nodes in cycles get a high rank (routed last)
    for nid in all_ids:
        if nid not in topo_order:
            topo_order[nid] = rank

    # Sort flows: upstream sources first (by src rank, then dst rank)
    sorted_flows = sorted(flow_matrix,
                          key=lambda fp: (topo_order.get(fp.src_id, rank),
                                          topo_order.get(fp.dst_id, rank)))

    results = []
    for fp in sorted_flows:
        src_pm = placed_lookup.get(fp.src_id)
        dst_pm = placed_lookup.get(fp.dst_id)
        if src_pm is None or dst_pm is None:
            results.append((fp, None))
            continue

        # Get ALL external belt points (outside machine, adjacent to face)
        all_out_bps = src_pm.output_belt_points()
        all_in_bps  = dst_pm.input_belt_points()

        if not all_out_bps or not all_in_bps:
            results.append((fp, None))
            continue

        # Pick the specific node assigned to this FlowPair
        src_node_idx = fp.src_node_idx % len(all_out_bps)
        dst_node_idx = fp.dst_node_idx % len(all_in_bps)

        # Preferred start/end points
        preferred_out = all_out_bps[src_node_idx]
        preferred_in  = all_in_bps[dst_node_idx]

        # Try the preferred pairing first, then fall back to any routable pair
        best_path, best_len = None, float('inf')

        candidates_out = [preferred_out] + [p for p in all_out_bps
                          if p != preferred_out and grid.in_bounds(*p) and grid.is_routable(*p)]
        candidates_in  = [preferred_in]  + [p for p in all_in_bps
                          if p != preferred_in  and grid.in_bounds(*p) and grid.is_routable(*p)]

        # Try preferred pair first
        if grid.in_bounds(*preferred_out) and grid.is_routable(*preferred_out) and            grid.in_bounds(*preferred_in)  and grid.is_routable(*preferred_in):
            path = astar(grid, preferred_out, preferred_in)
            if path is not None:
                best_path, best_len = path, len(path)

        # Fall back to any pair if preferred fails
        if best_path is None:
            for op in candidates_out:
                if not (grid.in_bounds(*op) and grid.is_routable(*op)):
                    continue
                for ip in candidates_in:
                    if not (grid.in_bounds(*ip) and grid.is_routable(*ip)):
                        continue
                    path = astar(grid, op, ip)
                    if path is not None and len(path) < best_len:
                        best_path, best_len = path, len(path)
                if best_path is not None:
                    break

        if best_path is not None and grid.place_belt(best_path, f"{fp.src_id}->{fp.dst_id}"):
            results.append((fp, best_path))
        else:
            results.append((fp, None))
    return results

print("astar() and route_belts() defined.")


# ── Feasibility repair ────────────────────────────────────────────────────────

def find_starved_connections(placed_machines, flow_matrix, belt_results):
    """
    Identify flow pairs that failed routing (no belt path).
    Returns list of (FlowPair, src_pm, dst_pm) for failed connections.
    """
    placed_lookup = {pm.instance_id: pm for pm in placed_machines}
    starved = []
    for fp, path in belt_results:
        if path is None:
            src_pm = placed_lookup.get(fp.src_id)
            dst_pm = placed_lookup.get(fp.dst_id)
            if src_pm and dst_pm:
                starved.append((fp, src_pm, dst_pm))
    return starved


def find_unconnected_ther_banks(placed_machines, belt_results):
    """
    Find thermal banks that have NO incoming belt with a battery material.
    These are the critical power failures.
    """
    battery_mats = set(BATTERY_POWER.keys()) - {'power'}
    ther_banks = [pm for pm in placed_machines if pm.machine_type.id == 'ther_bank']

    # Which ther_banks got a successful incoming belt?
    connected_tb_ids = set()
    for fp, path in belt_results:
        if path is not None and fp.material in battery_mats:
            if fp.dst_id.startswith('ther_bank_'):
                connected_tb_ids.add(fp.dst_id)

    return [tb for tb in ther_banks if tb.instance_id not in connected_tb_ids]


def try_place_depot_unloader_near(grid, target_pm, material='SC_bat'):
    """
    Try to place a depot_unloader adjacent to target_pm on a grid edge.
    Returns the PlacedMachine if successful, None otherwise.
    """
    mt = MACHINE_CATALOGUE['depot_unloader']

    # Try all 4 rotations and positions near the target
    candidates = []
    for rot in list(Rotation):
        w, h = mt.size(rot)
        # Try positions around the target machine
        for dy in range(-h, target_pm.h + 1):
            for dx in range(-w, target_pm.w + 1):
                x = target_pm.x + dx
                y = target_pm.y + dy
                if not grid.can_place(x, y, w, h):
                    continue
                if mt.edge_only and not grid.is_on_edge(x, y, w, h):
                    continue
                # Check distance to target
                dist = abs(x + w//2 - target_pm.x - target_pm.w//2) + \
                       abs(y + h//2 - target_pm.y - target_pm.h//2)
                candidates.append((dist, x, y, rot))

    if not candidates:
        return None

    # Pick closest valid position
    candidates.sort(key=lambda item: (item[0], item[1], item[2], item[3].value))
    dist, x, y, rot = candidates[0]
    w, h = mt.size(rot)

    # Create a unique instance id
    existing_ids = {pm.instance_id for pm in grid.placed_machines}
    idx = 0
    while f'depot_unloader_{idx}' in existing_ids:
        idx += 1

    pm = PlacedMachine(
        machine_type=mt, x=x, y=y, rotation=rot,
        instance_id=f'depot_unloader_{idx}',
        active_recipe=None)
    grid.place_machine(pm)
    return pm


def repair_feasibility(grid, placed_machines, flow_matrix, belt_results,
                       battery_item='SC_bat', verbose=True):
    """
    Post-routing repair pass.

    Priority order:
      1. Reconnect starved thermal banks (power is critical)
      2. Reconnect other starved production machines

    Strategies:
      A. Re-attempt routing with relaxed path (try all output/input point combos)
      B. Place a depot_unloader near the starved machine and route from it

    Returns (repaired_count, new_machines, new_belts)
    """
    placed_lookup = {pm.instance_id: pm for pm in placed_machines}
    repaired = 0
    new_machines = []
    new_belts = []
    battery_mats = set(BATTERY_POWER.keys()) - {'power'}

    # ── Phase 1: Thermal banks ────────────────────────────────────────────
    unconnected_tbs = find_unconnected_ther_banks(placed_machines, belt_results)

    if verbose and unconnected_tbs:
        print(f"  [REPAIR] {len(unconnected_tbs)} thermal bank(s) without power supply")

    for tb in unconnected_tbs:
        fixed = False

        # Strategy A: find ANY battery producer and try to route
        for pm in placed_machines:
            if pm.machine_type.id == 'packaging_unit' and pm.active_recipe is not None:
                recipe = pm.machine_type.recipes[pm.active_recipe]
                produces_battery = any(mat in battery_mats for mat, _ in recipe.outputs)
                if not produces_battery:
                    continue

                # Try all output→input point combinations
                out_pts = [(x, y) for x, y in pm.output_belt_points()
                           if grid.in_bounds(x, y) and grid.is_free(x, y)]
                in_pts  = [(x, y) for x, y in tb.input_belt_points()
                           if grid.in_bounds(x, y) and grid.is_free(x, y)]

                best_path = None
                best_len = float('inf')
                for op in out_pts:
                    for ip in in_pts:
                        path = astar(grid, op, ip)
                        if path and len(path) < best_len:
                            best_path, best_len = path, len(path)

                if best_path and grid.place_belt(best_path, f"{pm.instance_id}->{tb.instance_id}"):
                    bat_mat = next(mat for mat, _ in recipe.outputs if mat in battery_mats)
                    new_belts.append((pm.instance_id, tb.instance_id, bat_mat, best_path))
                    repaired += 1
                    fixed = True
                    if verbose:
                        print(f"  [REPAIR] Connected {tb.instance_id} ← {pm.instance_id} "
                              f"({best_len} cells)")
                    break

        # Strategy B: place a depot_unloader near the thermal bank
        if not fixed:
            depot = try_place_depot_unloader_near(grid, tb, battery_item)
            if depot:
                new_machines.append(depot)
                placed_machines.append(depot)
                placed_lookup[depot.instance_id] = depot

                # Route from depot to thermal bank
                out_pts = [(x, y) for x, y in depot.output_belt_points()
                           if grid.in_bounds(x, y) and grid.is_free(x, y)]
                in_pts  = [(x, y) for x, y in tb.input_belt_points()
                           if grid.in_bounds(x, y) and grid.is_free(x, y)]

                best_path = None
                best_len = float('inf')
                for op in out_pts:
                    for ip in in_pts:
                        path = astar(grid, op, ip)
                        if path and len(path) < best_len:
                            best_path, best_len = path, len(path)

                if best_path and grid.place_belt(best_path,
                        f"{depot.instance_id}->{tb.instance_id}"):
                    new_belts.append((depot.instance_id, tb.instance_id,
                                     battery_item, best_path))
                    repaired += 1
                    fixed = True
                    if verbose:
                        print(f"  [REPAIR] Placed {depot.instance_id} at "
                              f"({depot.x},{depot.y}) -> {tb.instance_id} "
                              f"({best_len} cells)")
                elif verbose:
                    print(f"  [REPAIR] Placed depot but could not route to "
                          f"{tb.instance_id}")
            elif verbose:
                print(f"  [REPAIR] FAILED: no space for depot near {tb.instance_id}")

    # ── Phase 2: Other starved machines ───────────────────────────────────
    starved = find_starved_connections(placed_machines, flow_matrix, belt_results)
    # Filter out thermal bank connections (already handled)
    starved = [(fp, s, d) for fp, s, d in starved
               if not d.instance_id.startswith('ther_bank_')]

    if verbose and starved:
        print(f"  [REPAIR] {len(starved)} other starved connection(s)")

    for fp, src_pm, dst_pm in starved:
        # Strategy A: re-attempt routing
        out_pts = [(x, y) for x, y in src_pm.output_belt_points()
                   if grid.in_bounds(x, y) and grid.is_free(x, y)]
        in_pts  = [(x, y) for x, y in dst_pm.input_belt_points()
                   if grid.in_bounds(x, y) and grid.is_free(x, y)]

        best_path = None
        best_len = float('inf')
        for op in out_pts:
            for ip in in_pts:
                path = astar(grid, op, ip)
                if path and len(path) < best_len:
                    best_path, best_len = path, len(path)

        if best_path and grid.place_belt(best_path, f"{fp.src_id}->{fp.dst_id}"):
            new_belts.append((fp.src_id, fp.dst_id, fp.material, best_path))
            repaired += 1
            if verbose:
                print(f"  [REPAIR] Reconnected {fp.src_id} -> {fp.dst_id} "
                      f"({fp.material}, {best_len} cells)")

    if verbose:
        print(f"  [REPAIR] Done: {repaired} connection(s) repaired, "
              f"{len(new_machines)} machine(s) added")

    return repaired, new_machines, new_belts


print("Feasibility repair tools defined:")
print("  find_starved_connections(), find_unconnected_ther_banks()")
print("  try_place_depot_unloader_near(), repair_feasibility()")

from collections import defaultdict, deque

@dataclass
class FitnessResult:
    mhc:                  float
    revenue:              float
    build_cost:           dict[str, int]
    all_placed:           bool
    paths_found:          int
    paths_total:          int
    belt_cells_used:      int
    total_power_demand:   float
    battery_power_output: float
    power_feasible:       bool
    chain_time:           float
    startup_time:         float
    self_sustaining:      bool
    belt_budget_used:     float
    feasible:             bool

def cull_unlinked_machines(
    grid: FactoryGrid, placed: list[PlacedMachine], belt_results: list[tuple[FlowPair, Optional[list[tuple[int, int]]]]]
) -> list[PlacedMachine]:
    """Removes machines that have no successful belt connections.
    Exempts main_unit and ther_bank (power sources)."""
    connected_ids = set()
    for fp, path in belt_results:
        if path is not None:
            connected_ids.add(fp.src_id)
            connected_ids.add(fp.dst_id)

    culled_placed = []
    # Work on a copy of the list so we can remove safely
    for pm in list(placed):
        # Never cull the main unit or power sources
        if pm.machine_type.id == "main_unit" or pm.machine_type.is_power_src:
            culled_placed.append(pm)
            continue

        if pm.instance_id in connected_ids:
            culled_placed.append(pm)
        else:
            grid.remove_machine(pm)

    return culled_placed

def calculate_metrics(
    grid: FactoryGrid,
    placed: list[PlacedMachine],
    flow_matrix: list[FlowPair],
    belt_results: list[tuple[FlowPair, Optional[list[tuple[int, int]]]]],
    chromosome_len: int,
    battery_item: str = 'SC_bat'
) -> FitnessResult:
    placed_lookup = {pm.instance_id: pm for pm in placed}
    proc_time: dict[str, int] = {}
    for pm in placed:
        if pm.active_recipe is not None and pm.machine_type.recipes:
            if pm.active_recipe < len(pm.machine_type.recipes):
                proc_time[pm.instance_id] = pm.machine_type.recipes[pm.active_recipe].process_time
            else:
                proc_time[pm.instance_id] = 0
        else:
            proc_time[pm.instance_id] = 0

    path_cache: dict[tuple[str, str], int] = {}
    mhc = 0.0; paths_found = 0; belt_cells_used = 0

    for fp, path in belt_results:
        if path is not None:
            dist = len(path) - 1
            mhc += fp.intensity * dist
            paths_found    += 1
            belt_cells_used += len(path)
            path_cache[(fp.src_id, fp.dst_id)] = dist
        else:
            src_pm = placed_lookup.get(fp.src_id)
            dst_pm = placed_lookup.get(fp.dst_id)
            if src_pm and dst_pm:
                dist = (abs(src_pm.x + src_pm.w//2 - dst_pm.x - dst_pm.w//2)
                      + abs(src_pm.y + src_pm.h//2 - dst_pm.y - dst_pm.h//2))
                mhc += fp.intensity * dist * 2
                path_cache[(fp.src_id, fp.dst_id)] = dist * 2
            else:
                penalty = grid.width + grid.height
                mhc += fp.intensity * penalty
                path_cache[(fp.src_id, fp.dst_id)] = penalty

    # 4. Revenue
    revenue = 0.0
    for pm in placed:
        if pm.active_recipe is not None and pm.machine_type.recipes:
            if pm.active_recipe < len(pm.machine_type.recipes):
                r = pm.machine_type.recipes[pm.active_recipe]
                for out_name, out_qty in r.outputs:
                    if out_name in REVENUE_TABLE:
                        revenue += REVENUE_TABLE[out_name] * (out_qty / max(r.process_time, 1))

    # 5. Build cost
    build_cost: dict[str, int] = {}
    for pm in placed:
        for mat, qty in pm.machine_type.build_cost:
            build_cost[mat] = build_cost.get(mat, 0) + qty

    # 6. Power gate
    total_demand = sum(pm.machine_type.power_cost for pm in placed)
    battery_count = sum(1 for pm in placed if pm.machine_type.id == 'ther_bank')
    bat_power    = BATTERY_POWER.get(battery_item, 0) * max(battery_count, 1)
    power_ok     = bat_power >= total_demand

    # 7. Self-sustainability gate: critical path through production DAG
    in_nodes:  dict[str, list[str]] = defaultdict(list)
    out_nodes: dict[str, list[str]] = defaultdict(list)
    all_nodes: set[str]             = set()
    for fp in flow_matrix:
        in_nodes[fp.dst_id].append(fp.src_id)
        out_nodes[fp.src_id].append(fp.dst_id)
        all_nodes.update([fp.src_id, fp.dst_id])

    indeg = {n: len(in_nodes[n]) for n in all_nodes}
    queue = deque(n for n in all_nodes if indeg[n] == 0)
    topo: list[str] = []
    while queue:
        node = queue.popleft()
        topo.append(node)
        for dst in out_nodes[node]:
            indeg[dst] -= 1
            if indeg[dst] == 0:
                queue.append(dst)

    arrival: dict[str, float] = {}
    for node in topo:
        pt = proc_time.get(node, 0)
        if not in_nodes[node]:
            arrival[node] = pt
        else:
            best = max(
                arrival.get(src, 0)
                + path_cache.get((src, node), grid.width + grid.height) / max(1, BELT_SPEED)
                for src in in_nodes[node]
            )
            arrival[node] = best + pt

    ther_bank_times = [v for k, v in arrival.items() if k.startswith('ther_bank_')]
    chain_time  = min(ther_bank_times) if ther_bank_times else float('inf')
    sum_proc    = sum(proc_time.get(n, 0) for n in all_nodes
                      if not n.startswith('ther_bank_'))
    belt_secs   = max(0.0, chain_time - sum_proc)
    sustain_ok  = chain_time <= SIM_EQ_MAX_TICKS

    # 8. Aggregate
    # all_placed evaluates against the ORIGINAL chromosome len
    all_placed = len(placed) == chromosome_len
    paths_total = len(flow_matrix)
    feasible   = power_ok and sustain_ok and all_placed and (paths_found == paths_total)

    return FitnessResult(
        mhc=mhc, revenue=revenue, build_cost=build_cost,
        all_placed=all_placed, paths_found=paths_found,
        paths_total=paths_total, belt_cells_used=belt_cells_used,
        total_power_demand=total_demand,
        battery_power_output=bat_power, power_feasible=power_ok,
        chain_time=chain_time, startup_time=chain_time,
        self_sustaining=sustain_ok, belt_budget_used=belt_secs,
        feasible=feasible,
    )

def evaluate_fitness(
    chromosome:   Chromosome,
    battery_item: str = 'SC_bat',
) -> tuple[FitnessResult, FactoryGrid, list[FlowPair]]:
    """Full fitness evaluation with 3-gate feasibility model."""

    # 1. Decode chromosome -> grid
    grid   = FactoryGrid()
    placed = blf_decode(chromosome, grid)

    # 2. Derive flow matrix from recipes
    flow_matrix   = derive_flow_matrix(placed)
    placed_lookup = {pm.instance_id: pm for pm in placed}

    # 3. Route belts
    belt_results = route_belts(grid, placed_lookup, flow_matrix)

    # 3.5 Repair starved connections (power priority)
    rep_count, rep_machines, rep_belts = repair_feasibility(
        grid, placed, flow_matrix, belt_results,
        battery_item=battery_item, verbose=False)
    if rep_belts:
        for src_id, dst_id, mat, path in rep_belts:
            fp_rep = FlowPair(src_id=src_id, dst_id=dst_id, material=mat, intensity=1.0)
            belt_results.append((fp_rep, path))

    # 3.6 Cull unlinked machines
    placed = cull_unlinked_machines(grid, placed, belt_results)

    # 4-8. Calculate metrics
    res = calculate_metrics(grid, placed, flow_matrix, belt_results, len(chromosome.genes), battery_item)
    return res, grid, flow_matrix

print("FitnessResult, calculate_metrics() and evaluate_fitness() defined.")



COLOUR_MAP = {
    "main_unit":         "#2C3E50",
    "ther_bank":         "#F1C40F",
    "refining_unit":     "#E74C3C",
    "shredding_unit":    "#E67E22",
    "fitting_unit":      "#27AE60",
    "moulding_unit":     "#2980B9",
    "grinding_unit":     "#F39C12",
    "filling_unit":      "#8E44AD",
    "packaging_unit":    "#16A085",
    "planting_unit":     "#2ECC71",
    "seed_picking_unit": "#1ABC9C",
    "stash":             "#95A5A6",
    "depot_loader":      "#3498DB",
    "depot_unloader":    "#9B59B6",
}


def print_grid(grid, flow_matrix):
    """Fallback ASCII representation of the grid."""
    print("\n--- ASCII GRID FALLBACK ---")

    # 1. Build a 2D array of chars
    arr = [['.' for _ in range(grid.width)] for _ in range(grid.height)]

    # 2. Mark belts
    for _, path in grid.belt_paths:
        for x, y in path:
            if grid.in_bounds(x, y):
                arr[y][x] = '*'

    # 3. Mark machines
    for pm in grid.placed_machines:
        # Use first letter of machine ID
        char = pm.machine_type.id[0].upper()
        for dy in range(pm.h):
            for dx in range(pm.w):
                if grid.in_bounds(pm.x + dx, pm.y + dy):
                    arr[pm.y + dy][pm.x + dx] = char

    # 4. Print
    # Print column numbers (tens)
    print("   " + "".join([str(i // 10) if i % 10 == 0 else " " for i in range(grid.width)]))
    # Print column numbers (units)
    print("   " + "".join([str(i % 10) for i in range(grid.width)]))

    for y in range(grid.height):
        row_str = "".join(arr[y])
        print(f"{y:2d} {row_str}")
    print("---------------------------\n")


def plot_layout(
    grid:        FactoryGrid,
    result:      FitnessResult,
    flow_matrix: list[FlowPair],
    save_path:   str = "layout_merged.png",
    zpf_zone:    ZPF = None,
    title_str:   str = None,
):
    """Matplotlib visualisation of the factory layout."""
    if not HAS_MPL:
        print("[SKIP] matplotlib not available.")
        return

    fig, ax = plt.subplots(figsize=(13, 13))
    ax.set_xlim(0, grid.width)
    ax.set_ylim(0, grid.height)
    ax.set_aspect('equal')
    ax.invert_yaxis()

    for x in range(grid.width + 1):
        ax.axvline(x, color='#E0E0E0', linewidth=0.3, zorder=0)
    for y in range(grid.height + 1):
        ax.axhline(y, color='#E0E0E0', linewidth=0.3, zorder=0)

    seen_types    = {}
    placed_lookup = {}
    for pm in grid.placed_machines:
        placed_lookup[pm.instance_id] = pm
        color = COLOUR_MAP.get(pm.machine_type.id, '#BDC3C7')
        ax.add_patch(plt.Rectangle(
            (pm.x, pm.y), pm.w, pm.h,
            facecolor=color, edgecolor='#2C3E50',
            linewidth=1.5, alpha=0.85, zorder=2))
        ax.text(pm.x + pm.w / 2, pm.y + pm.h / 2,
                pm.machine_type.display_name.replace(' ', '\n'),
                ha='center', va='center',
                fontsize=5.5, color='white', fontweight='bold', zorder=3)
        # Draw ALL input nodes (coloured by slot index)
        slot_colors = ['#e74c3c', '#e67e22', '#9b59b6', '#1abc9c', '#3498db', '#e91e63']
        for slot_i, (nx, ny) in enumerate(pm.input_belt_points()):
            col = slot_colors[slot_i % len(slot_colors)]
            ax.plot(nx + 0.5, ny + 0.5, 's', color=col, markersize=3.5, zorder=4)
        # Draw ALL output nodes (green triangle, slightly lighter per slot)
        for slot_i, (nx, ny) in enumerate(pm.output_belt_points()):
            alpha = 0.6 + 0.1 * (slot_i % 4)
            ax.plot(nx + 0.5, ny + 0.5, '^', color='#2ecc71', markersize=3.5,
                    alpha=min(alpha, 1.0), zorder=4)
        seen_types[pm.machine_type.display_name] = color

    for label, path in grid.belt_paths:
        xs = [p[0] + 0.5 for p in path]
        ys = [p[1] + 0.5 for p in path]
        ax.plot(xs, ys, '-', color='#f39c12', linewidth=1.5, alpha=0.8, zorder=1.5)

    for fp in flow_matrix:
        src_pm = placed_lookup.get(fp.src_id)
        dst_pm = placed_lookup.get(fp.dst_id)
        if src_pm is None or dst_pm is None:
            continue
        out_pts = src_pm.output_belt_points()
        in_pts  = dst_pm.input_belt_points()
        if not out_pts or not in_pts:
            continue
        snx, sny = out_pts[fp.src_node_idx % len(out_pts)]
        dnx, dny = in_pts[fp.dst_node_idx  % len(in_pts)]
        ax.annotate('', xy=(dnx + 0.5, dny + 0.5), xytext=(snx + 0.5, sny + 0.5),
                    arrowprops=dict(arrowstyle='->', color='#E74C3C',
                                    lw=min(2.0, fp.intensity * 0.35), alpha=0.5), zorder=5)

    patches = [mpatches.Patch(color=c, label=name) for name, c in seen_types.items()]
    patches.append(mpatches.Patch(color='#f39c12', label='Belt'))
    patches.append(plt.Line2D([0], [0], marker='s', color='w',
                               markerfacecolor='#e74c3c', markersize=6, label='Input Node'))
    patches.append(plt.Line2D([0], [0], marker='^', color='w',
                               markerfacecolor='#2ecc71', markersize=6, label='Output Node'))
    ax.legend(handles=patches, loc='lower right', fontsize=7, framealpha=0.9, ncol=2)

    feas_str = "FEASIBLE" if result.feasible else "INFEASIBLE"
    if title_str:
        ax.set_title(title_str, fontsize=11, fontweight='bold')
    else:
        ax.set_title(
            f'Valley IV Factory Layout - BLF Decode (seed=42)\n'
            f'MHC={result.mhc:.0f}  |  Rev={result.revenue:.2f} cr/tick  |  '
            f'Power {"OK" if result.power_feasible else "DEFICIT"}  |  '
            f'Chain={result.chain_time:.1f}t/{SIM_EQ_MAX_TICKS}t  |  '
            f'Paths {result.paths_found}/{result.paths_total}  |  '
            f'{feas_str}',
            fontsize=9)
            
    if zpf_zone is not None:
        ax.add_patch(plt.Rectangle((zpf_zone.x, zpf_zone.y), zpf_zone.w, zpf_zone.h,
                                   facecolor='red', alpha=0.3, edgecolor='red', hatch='//', zorder=5, label='Ground Zero'))
        # r1 and r2 circles
        ax.add_patch(plt.Circle((zpf_zone.x + zpf_zone.w/2, zpf_zone.y + zpf_zone.h/2), zpf_zone.r1, color='red', fill=False, linestyle='--', zorder=5, label='Flexible Zone'))
        ax.add_patch(plt.Circle((zpf_zone.x + zpf_zone.w/2, zpf_zone.y + zpf_zone.h/2), zpf_zone.r2, color='orange', fill=False, linestyle='--', zorder=5, label='Penalty Zone'))

    ax.set_xlabel('Grid X')
    ax.set_ylabel('Grid Y')
    plt.tight_layout()
    plt.savefig(save_path, dpi=150, bbox_inches='tight')
    plt.show()
    print(f"Saved to {save_path}")

print("plot_layout() defined.")



def plot_gantt(engine, eq_tick=None, max_ticks=120):
    """Machine status over time (Gantt chart)."""
    if not HAS_MPL:
        print("[SKIP] matplotlib not available"); return

    STATUS_COLOUR = {
        'idle':    '#95A5A6',
        'running': '#27AE60',
        'starved': '#E74C3C',
        'blocked': '#F39C12',
    }
    machine_ids = sorted(engine.states.keys())
    if not machine_ids:
        print("[SKIP] No machines to plot."); return

    fig, ax = plt.subplots(figsize=(14, max(4, len(machine_ids) * 0.35)))
    ticks = min(max_ticks, engine.tick_count)

    for row, mid in enumerate(machine_ids):
        state = engine.states[mid]
        history = state.status_history[:ticks]
        for t, status in enumerate(history):
            color = STATUS_COLOUR.get(status, '#BDC3C7')
            ax.barh(row, 1, left=t, height=0.8, color=color, edgecolor='none')

    if eq_tick is not None and eq_tick <= ticks:
        ax.axvline(eq_tick, color='#2C3E50', linestyle='--', linewidth=1.5, label=f'Eq @ {eq_tick}')

    ax.set_yticks(range(len(machine_ids)))
    ax.set_yticklabels([mid.split('_')[0][:8] for mid in machine_ids], fontsize=6)
    ax.set_xlabel('Tick')
    ax.set_title('Machine Status Gantt Chart', fontsize=11)
    ax.invert_yaxis()

    patches = [mpatches.Patch(color=c, label=s) for s, c in STATUS_COLOUR.items()]
    ax.legend(handles=patches, loc='lower right', fontsize=7, ncol=4)
    plt.tight_layout()
    plt.show()


def plot_throughput(engine, window=10):
    """Cumulative production over time."""
    if not HAS_MPL:
        print("[SKIP] matplotlib not available"); return
    if not engine.production_log:
        print("[SKIP] No production data."); return

    materials = {}
    for tick, iid, mat, qty in engine.production_log:
        if mat not in materials:
            materials[mat] = {}
        materials[mat][tick] = materials[mat].get(tick, 0) + qty

    fig, ax = plt.subplots(figsize=(12, 5))
    colors = plt.cm.tab20.colors
    for idx, (mat, tick_data) in enumerate(sorted(materials.items())):
        ticks_sorted = sorted(tick_data.keys())
        cumulative = []
        total = 0
        for t in ticks_sorted:
            total += tick_data[t]
            cumulative.append(total)
        ax.plot(ticks_sorted, cumulative, '-', color=colors[idx % 20],
                linewidth=1.5, label=mat, alpha=0.85)

    ax.set_xlabel('Tick')
    ax.set_ylabel('Cumulative Units Produced')
    ax.set_title('Production Throughput', fontsize=11)
    ax.legend(fontsize=7, ncol=3, loc='upper left')
    ax.grid(alpha=0.3)
    plt.tight_layout()
    plt.show()


print("plot_layout(), plot_gantt(), plot_throughput() defined.")






@dataclass
class BeltPath:
    """A routed belt connection between two machine instances.
    path is the actual sequence of (x,y) grid cells from source output
    connect point to destination input connect point."""
    src_id:    str              # instance_id of source machine
    dst_id:    str              # instance_id of destination machine
    material:  str              # material flowing on this belt
    path:      list             # [(x0,y0), ..., (xN,yN)]
    intensity: float

    @property
    def transit_ticks(self) -> int:
        """Ticks to traverse this belt path (1 cell = 1 tick)."""
        return max(1, len(self.path) - 1)


@dataclass
class InTransitItem:
    """One unit of material currently moving along a belt path."""
    material:      str
    qty:           float
    path_idx:      int      # index into SimEngine.belt_paths
    ticks_elapsed: int = 0

    def current_cell(self, belt_paths: list) -> tuple:
        bp  = belt_paths[self.path_idx]
        idx = min(self.ticks_elapsed, len(bp.path) - 1)
        return bp.path[idx]

    def is_delivered(self, belt_paths: list) -> bool:
        return self.ticks_elapsed >= belt_paths[self.path_idx].transit_ticks


@dataclass
class MachineSimState:
    """Runtime production state for one placed machine instance.

    status:
      'idle'    – no recipe running
      'running' – recipe countdown active
      'starved' – tried to start but input buffer insufficient
      'blocked' – output buffer full (not modelled; reserved)
    """
    instance_id:        str
    placed:             object            # PlacedMachine reference

    buffer_in:          dict = field(default_factory=dict)
    buffer_out:         dict = field(default_factory=dict)
    active_recipe_idx:  object = None    # int or None
    ticks_remaining:    int    = 0
    status:             str    = 'idle'
    status_history:     list   = field(default_factory=list)
    runs_completed:     int    = 0


print("Simulation data structures defined: BeltPath, InTransitItem, MachineSimState")

def build_belt_paths(
    grid:        FactoryGrid,
    flow_matrix: list,          # list[FlowPair] — instance-level, from derive_flow_matrix()
) -> list:
    """Convert grid.belt_paths into BeltPath simulation objects.

    grid.belt_paths stores (label, path) where label = "{src_id}->{dst_id}".
    We cross-reference with flow_matrix to find the material each belt carries.
    """
    # Build lookup: (src_id, dst_id) -> FlowPair
    flow_lookup = {}
    for fp in flow_matrix:
        flow_lookup[(fp.src_id, fp.dst_id)] = fp

    belt_paths = []
    for label, path in grid.belt_paths:
        # Label format: "{src_instance_id}->{dst_instance_id}"
        if '->' not in label:
            continue
        src_id, dst_id = label.split('->', 1)
        fp = flow_lookup.get((src_id, dst_id))
        if fp is None:
            continue
        belt_paths.append(BeltPath(
            src_id    = src_id,
            dst_id    = dst_id,
            material  = fp.material,
            path      = list(path),
            intensity = fp.intensity,
        ))

    return belt_paths


def find_dag_roots(
    placed_machines: list,
    flow_matrix:     list,
) -> set:
    """Instance IDs that have NO incoming flow pairs.
    These are the start of production chains — they receive free raw
    material injection each tick (simulating depot loader supply)."""
    has_incoming = {fp.dst_id for fp in flow_matrix}
    return {
        pm.instance_id
        for pm in placed_machines
        if pm.instance_id not in has_incoming
        and pm.machine_type.recipes               # skip utilities
    }


print("build_belt_paths() and find_dag_roots() defined.")

class SimEngine:
    """Discrete-time factory simulation.

    One tick = one simulation time unit.
    Belt speed = 1 cell / tick.
    Machine speed = recipe.process_time ticks per run.

    Designed to run AFTER evaluate_fitness() has placed machines and belts.
    """

    def __init__(
        self,
        placed_machines: list,
        belt_paths:      list,
        flow_matrix:     list,
        revenue_table:   dict,
        raw_supply_ids:  set  = None,
        inject_every:    int  = 1,
    ):
        self.belt_paths     = belt_paths
        self.revenue_table  = revenue_table
        self.inject_every   = inject_every
        self.raw_supply_ids = raw_supply_ids or set()

        # One state per placed machine instance
        self.states: dict = {}
        for pm in placed_machines:
            self.states[pm.instance_id] = MachineSimState(
                instance_id=pm.instance_id,
                placed=pm,
            )

        self.in_transit:      list = []
        self.production_log:  list = []   # [(tick, instance_id, material, qty)]
        self.total_produced:  dict = {}
        self.tick_count:      int  = 0
        self.snapshots:       list = []
        self._snapshot_every: int  = 5

        # Fractional accumulator for sub-tick supply rates
        self._accum: dict[tuple[str, str], float] = {}
        # Supply rates per tick: 250 ferri/min=4.17/tick, 60 ori/min=1.0/tick, 30 ame/min=0.5/tick
        self.supply_rates: dict[str, float] = {
            'ferri_ore': 3.0 * TICK_SECONDS, 'ori_ore': 5.0 * TICK_SECONDS, 'ame_ore': 3.0 * TICK_SECONDS,
            'buckflower': 1.0 * TICK_SECONDS, 'sandleaf': 0.5 * TICK_SECONDS, 'citrome': 1.0 * TICK_SECONDS, 'aketine': 0.5 * TICK_SECONDS,
        }

    # ── Core tick ─────────────────────────────────────────────────────────────

    def tick(self) -> None:
        t = self.tick_count = self.tick_count + 1

        # Step 1: advance belt items
        still_moving = []
        for item in self.in_transit:
            item.ticks_elapsed += 1
            if item.is_delivered(self.belt_paths):
                bp    = self.belt_paths[item.path_idx]
                state = self.states.get(bp.dst_id)
                if state is not None:
                    buf = state.buffer_in
                    buf[item.material] = buf.get(item.material, 0) + item.qty
            else:
                still_moving.append(item)
        self.in_transit = still_moving

        # Step 2: inject raw materials into DAG root machines (fractional accumulator)
        # Supply rates (per tick): ferri=4.17, ori=1.0, ame=0.5
        # Uses fractional accumulators so partial-tick supply is never lost
        for iid in self.raw_supply_ids:
            state = self.states.get(iid)
            if state is None:
                continue
            pm  = state.placed
            if pm.active_recipe is None or not pm.machine_type.recipes:
                continue
            ridx = min(pm.active_recipe, len(pm.machine_type.recipes) - 1)
            for mat, qty in pm.machine_type.recipes[ridx].inputs:
                rate = self.supply_rates.get(mat, 0.0)
                if rate <= 0:
                    rate = float(qty) / max(1.0, pm.machine_type.recipes[ridx].process_time / 2.0)
                key = (iid, mat)
                self._accum[key] = self._accum.get(key, 0.0) + rate
                inject_qty = int(self._accum[key])
                if inject_qty > 0:
                    state.buffer_in[mat] = state.buffer_in.get(mat, 0) + inject_qty
                    self._accum[key] -= inject_qty

        # Step 3: complete running recipes
        for state in self.states.values():
            if state.status != 'running':
                continue
            state.ticks_remaining -= 1
            if state.ticks_remaining <= 0:
                pm   = state.placed
                ridx = state.active_recipe_idx
                rec  = pm.machine_type.recipes[ridx]
                for out_mat, out_qty in rec.outputs:
                    state.buffer_out[out_mat] = (
                        state.buffer_out.get(out_mat, 0) + out_qty)
                    self.production_log.append(
                        (t, state.instance_id, out_mat, out_qty))
                    self.total_produced[out_mat] = (
                        self.total_produced.get(out_mat, 0) + out_qty)
                state.runs_completed    += 1
                state.active_recipe_idx  = None
                state.ticks_remaining    = 0
                state.status             = 'idle'

        # Step 4: start new recipes (idle or starved machines)
        for state in self.states.values():
            if state.status not in ('idle', 'starved'):
                continue
            pm = state.placed
            if pm.active_recipe is None or not pm.machine_type.recipes:
                state.status = 'idle'
                continue
            ridx = min(pm.active_recipe, len(pm.machine_type.recipes) - 1)
            rec  = pm.machine_type.recipes[ridx]
            # Check input buffer has all required materials
            if all(state.buffer_in.get(mat, 0) >= qty
                   for mat, qty in rec.inputs):
                for mat, qty in rec.inputs:
                    state.buffer_in[mat] -= qty
                state.active_recipe_idx = ridx
                state.ticks_remaining   = max(1, round(rec.process_time / TICK_SECONDS))
                state.status            = 'running'
            else:
                state.status = 'starved'

        # Step 5: dispatch output to belt paths
        for state in self.states.values():
            if not state.buffer_out:
                continue
            for path_idx, bp in enumerate(self.belt_paths):
                if bp.src_id != state.instance_id:
                    continue
                qty_avail = state.buffer_out.get(bp.material, 0)
                if qty_avail <= 0:
                    continue
                qty_send = min(1.0, qty_avail)
                state.buffer_out[bp.material] -= qty_send
                self.in_transit.append(InTransitItem(
                    material=bp.material, qty=qty_send,
                    path_idx=path_idx, ticks_elapsed=0))

        # Step 6: record status history
        for state in self.states.values():
            state.status_history.append(state.status)

        # Step 7: snapshot
        if t <= 20 or t % self._snapshot_every == 0:
            self.snapshots.append({
                'tick'          : t,
                'in_transit'    : [(it.path_idx, it.ticks_elapsed,
                                    it.material, it.qty)
                                   for it in self.in_transit],
                'statuses'      : {iid: s.status
                                   for iid, s in self.states.items()},
                'total_produced': dict(self.total_produced),
                'buffer_in'     : {iid: dict(s.buffer_in)
                                   for iid, s in self.states.items()},
            })

    # ── Equilibrium ───────────────────────────────────────────────────────────

    def is_equilibrium(self, window: int = 30, threshold: float = 0.08) -> bool:
        """True when production rate is stable across two consecutive windows."""
        if self.tick_count < window * 2:
            return False

        def rate(log_slice):
            counts = {}
            for _, _, mat, qty in log_slice:
                counts[mat] = counts.get(mat, 0) + qty
            return counts

        r1 = rate(self.production_log[-window:])
        r2 = rate(self.production_log[-window * 2 : -window])
        if not r1 or not r2:
            return False
        for mat in set(r1) | set(r2):
            v1, v2 = r1.get(mat, 0.0), r2.get(mat, 0.0)
            if v2 == 0:
                if v1 > 0: return False
                continue
            if abs(v1 - v2) / v2 > threshold:
                return False
        return True

    def run(self, max_ticks: int = 400, window: int = 30,
            threshold: float = 0.08, verbose: bool = True) -> object:
        """Run until equilibrium or max_ticks. Returns equilibrium tick or None."""
        eq_tick = None
        for _ in range(max_ticks):
            self.tick()
            if eq_tick is None and self.is_equilibrium(window, threshold):
                eq_tick = self.tick_count
        if verbose:
            if eq_tick:
                print(f"  Equilibrium at tick {eq_tick} / {max_ticks}")
            else:
                print(f"  No equilibrium within {max_ticks} ticks")
        return eq_tick

    # ── Metrics ───────────────────────────────────────────────────────────────

    def throughput_at_equilibrium(self, window: int = 30) -> dict:
        """Mean units/tick per material over the last `window` ticks."""
        log = self.production_log[-window:]
        counts = {}
        for _, _, mat, qty in log:
            counts[mat] = counts.get(mat, 0) + qty
        return {mat: qty / window for mat, qty in counts.items()}

    def simulated_revenue_per_tick(self, window: int = 30) -> float:
        """Revenue/tick at equilibrium — more accurate than analytical estimate."""
        thr = self.throughput_at_equilibrium(window)
        return sum(
            self.revenue_table.get(mat, 0) * rate
            for mat, rate in thr.items()
        )

    def pipeline_latencies(self) -> list:
        """Transit time per belt path, sorted by descending latency."""
        return sorted(
            [{'src': bp.src_id, 'dst': bp.dst_id,
              'material': bp.material,
              'path_len': len(bp.path),
              'transit_ticks': bp.transit_ticks,
              'intensity': bp.intensity}
             for bp in self.belt_paths],
            key=lambda x: -x['transit_ticks']
        )


print("SimEngine defined.")
print("Methods: tick(), run(), is_equilibrium(), throughput_at_equilibrium(),")
print("         simulated_revenue_per_tick(), pipeline_latencies()")





def evaluate_with_simulation(
    chromosome:    object,           # Chromosome
    battery_item:  str  = 'SC_bat',
    max_sim_ticks: int  = 350,
    eq_window:     int  = 30,
    eq_threshold:  float= 0.08,
    verbose:       bool = True,
) -> tuple:
    """
    Full evaluation = static fitness + discrete-time simulation.

    Returns
    -------
    (FitnessResult, FactoryGrid, flow_matrix, SimEngine, eq_tick)

    Gate 2 update
    -------------
    Gate 2 (self-sustainability) is now checked against the *simulation* result:
      equilibrium_tick <= SIM_EQ_MAX_TICKS ticks
    If no equilibrium is reached, Gate 2 fails regardless of analytical chain_time.
    The FitnessResult.self_sustaining and FitnessResult.feasible flags are
    updated in-place to reflect the simulation result.
    """
    # 1. Static evaluation (existing pipeline)
    result, grid, flow_matrix = evaluate_fitness(chromosome, battery_item)

    if verbose:
        print(f"Static evaluation done:")
        print(f"  MHC={result.mhc:.1f}  revenue={result.revenue:.2f}  "
              f"chain_time={result.chain_time:.1f} ticks  "
              f"feasible={result.feasible}")

    # 2. Build simulation inputs
    belt_paths      = build_belt_paths(grid, flow_matrix)
    raw_supply_ids  = find_dag_roots(grid.placed_machines, flow_matrix)

    if verbose:
        print(f"  Belt paths for simulation: {len(belt_paths)}")
        print(f"  Raw supply sources (DAG roots): {raw_supply_ids}")

    # 3. Run simulation
    engine = SimEngine(
        placed_machines = grid.placed_machines,
        belt_paths      = belt_paths,
        flow_matrix     = flow_matrix,
        revenue_table   = REVENUE_TABLE,
        raw_supply_ids  = raw_supply_ids,
        inject_every    = 1,
    )
    eq_tick = engine.run(
        max_ticks=max_sim_ticks,
        window=eq_window,
        threshold=eq_threshold,
        verbose=verbose,
    )

    # 4. Update Gate 2 with simulation result
    sim_sustain = eq_tick is not None and eq_tick <= SIM_EQ_MAX_TICKS
    result.self_sustaining = sim_sustain
    result.startup_time    = eq_tick if eq_tick else float('inf')
    result.feasible        = (result.power_feasible
                               and sim_sustain
                               and result.all_placed)

    if verbose:
        sim_rev = engine.simulated_revenue_per_tick(window=eq_window)
        print(f"  Sim revenue/tick (at eq): {sim_rev:.3f}  "
              f"(static: {result.revenue:.3f})")
        print(f"  Gate 2 (simulation):  "
              f"{'PASS' if sim_sustain else 'FAIL'}  "
              f"(eq_tick={eq_tick} ≤ {SIM_EQ_MAX_TICKS}?)")
        print(f"  Overall feasible: {result.feasible}")

    return result, grid, flow_matrix, engine, eq_tick


print("evaluate_with_simulation() defined.")
print(f"Gate 2 now: equilibrium_tick ≤ SIM_EQ_MAX_TICKS ({SIM_EQ_MAX_TICKS} ticks)")

def evaluate_search_fitness(chromosome, battery_item):
    """
    Simulation-aware fitness for search functions.
    1. Run static evaluation (fast gate check)
    2. If all 3 static gates pass, run a short simulation
    3. Use -sim_revenue as the MHC value (so minimisation = maximise revenue)
    """
    res, grid, fm = evaluate_fitness(chromosome, battery_item)
    if res.feasible:
        sim_res, _, _, _, eq_tick = evaluate_with_simulation(
            chromosome, battery_item,
            max_sim_ticks=80, eq_window=15, verbose=False)
        if eq_tick is not None:
            sim_rev = sim_res.revenue
            res.mhc = -sim_rev   # negative so that minimisation maximises revenue
        else:
            res.mhc = 999999.0   # no equilibrium = worst score
    return res, grid, fm

print('evaluate_search_fitness() defined.')
print('  Static gates filter first, then short 80-tick simulation ranks survivors.')


def greedy_rotation_search(
    base_chromo:  Chromosome,
    battery_item: str = 'SC_bat',
    n_passes:     int = 2,
) -> tuple[Chromosome, float]:
    """
    Greedy per-gene rotation optimisation.
    For each gene, try all 4 rotations, keep the best (lowest MHC).
    Repeat for n_passes.
    """
    best_chromo = base_chromo.copy()
    best_res, _, _ = evaluate_search_fitness(best_chromo, battery_item)
    best_mhc = best_res.mhc

    for pass_n in range(n_passes):
        improved = False
        for i in range(len(best_chromo.genes)):
            for rot in list(Rotation):
                candidate = best_chromo.copy()
                candidate.genes[i].rotation = rot
                res, _, _ = evaluate_search_fitness(candidate, battery_item)
                if res.mhc < best_mhc:
                    best_mhc    = res.mhc
                    best_chromo = candidate
                    improved    = True
        print(f"  Pass {pass_n + 1}: MHC = {best_mhc:.1f}  {'(improved)' if improved else '(no change)'}")
        if not improved:
            break

    return best_chromo, best_mhc



from dataclasses import dataclass, field
from typing import Dict, List, Tuple, Optional
import itertools


@dataclass
class ProductSpec:
    """
    Complete description of a production chain for one revenue product.

    Attributes
    ----------
    name            : output item name (must be in REVENUE_TABLE)
    revenue         : credits per unit of output
    chain_depth     : number of processing steps in the critical path
    raw_materials   : {material: qty_per_output_unit}  — depot loader inputs
    machine_types   : {machine_type_id: count}  — machines needed per line
    total_power     : total power demand of all machines in one line
    critical_path_s : critical path process time (excluding belt travel)
    terminal_recipe : (machine_type_id, recipe_idx) of the final machine
    power_battery   : which battery item feeds the ther_bank for this chain
    """
    name:             str
    revenue:          int
    chain_depth:      int
    raw_materials:    Dict[str, int]
    machine_types:    Dict[str, int]
    total_power:      int
    critical_path_s:  int
    terminal_recipe:  Tuple[str, int]
    power_battery:    str = 'SC_bat'

    def revenue_per_power(self) -> float:
        return self.revenue / max(self.total_power, 1)

    def revenue_per_depth(self) -> float:
        return self.revenue / max(self.chain_depth, 1)

    def footprint_cells(self) -> int:
        """Approximate grid cells consumed by one production line."""
        total = 0
        for mid, count in self.machine_types.items():
            mt = MACHINE_CATALOGUE[mid]
            total += mt.base_w * mt.base_h * count
        return total


# ── All viable product specs (derived from recipe graph) ─────────────────────
ALL_PRODUCTS: Dict[str, ProductSpec] = {

    # ── Filling products (rev=70) ─────────────────────────────────────────────
    # buck_cap_A: steel_bottle×10 + ground_buck_pow×10 -> buck_cap_A
    #   steel chain:  ferri_ore -> refin(r2) -> ferrium -> shred(r1) -> ferri_pow
    #                 -> grind(r3)×2ferri_pow -> dense_ferri_pow -> refin(r10) -> steel
    #                 -> mould(r0)×2steel -> steel_bottle
    #   buck chain:   buckflower -> shred(r5) -> buck_pow×2
    #                 sandleaf -> shred(r7) -> sandleaf_pow×2  (common_extra for grind r0)
    #                 grind(r0): buck_pow×2 + sandleaf_pow×1 -> ground_buck_pow
    'buck_cap_A': ProductSpec(
        name='buck_cap_A', revenue=70, chain_depth=5,
        raw_materials={'ferri_ore': 40, 'buckflower': 10, 'sandleaf': 5},
        machine_types={
            'refining_unit': 2, 'shredding_unit': 3,
            'grinding_unit': 2, 'moulding_unit': 1, 'filling_unit': 1,
        },
        total_power = 2*10 + 3*10 + 2*20 + 1*10 + 1*20,  # 120
        critical_path_s = 5 * 2,   # 5 processing steps × 2s each = 10s + belt
        terminal_recipe = ('filling_unit', 0),
        power_battery = 'SC_bat',
    ),

    # can_cit_A: replace ground_buck_pow with ground_citrome_pow
    #   citrome chain: citrome -> shred(r6) -> citrome_pow×2 -> grind(r5)×2 -> ground_citrome_pow
    'can_cit_A': ProductSpec(
        name='can_cit_A', revenue=70, chain_depth=5,
        raw_materials={'ferri_ore': 40, 'citrome': 10},
        machine_types={
            'refining_unit': 2, 'shredding_unit': 2,
            'grinding_unit': 2, 'moulding_unit': 1, 'filling_unit': 1,
        },
        total_power = 2*10 + 2*10 + 2*20 + 1*10 + 1*20,  # 110
        critical_path_s = 5 * 2,
        terminal_recipe = ('filling_unit', 1),
        power_battery = 'SC_bat',
    ),

    # ── Packaging products ────────────────────────────────────────────────────
    # SC_bat (rev=30): ferri_part×10 + ori_pow×15 -> SC_bat
    #   ferri_part: ferri_ore -> refin(r2) -> ferrium -> fit(r1) -> ferri_part
    #   ori_pow:    ori_ore -> shred(r0) -> ori_pow
    'SC_bat': ProductSpec(
        name='SC_bat', revenue=30, chain_depth=3,
        raw_materials={'ferri_ore': 10, 'ori_ore': 15},
        machine_types={
            'refining_unit': 1, 'fitting_unit': 1,
            'shredding_unit': 1, 'packaging_unit': 1,
        },
        total_power = 10 + 10 + 10 + 20,   # 50
        critical_path_s = 3 * 2,
        terminal_recipe = ('packaging_unit', 2),
        power_battery = 'SC_bat',
    ),

    # HC_bat (rev=27): steel_part×10 + dense_ori_pow×15 -> HC_bat
    #   steel: ferri_ore -> refin -> shred -> grind -> refin -> fit
    #   dense_ori_pow: ori_ore -> shred -> ori_pow -> grind(r1)×2 -> dense_ori_pow
    'HC_bat': ProductSpec(
        name='HC_bat', revenue=27, chain_depth=5,
        raw_materials={'ferri_ore': 10, 'ori_ore': 30},
        machine_types={
            'refining_unit': 2, 'shredding_unit': 2,
            'grinding_unit': 2, 'fitting_unit': 1, 'packaging_unit': 1,
        },
        total_power = 2*10 + 2*10 + 2*20 + 1*10 + 1*20,  # 110
        critical_path_s = 5 * 2,
        terminal_recipe = ('packaging_unit', 0),
        power_battery = 'HC_bat',  # HC_bat powers HC_bat chain (1100 >> 110)
    ),

    # LC_bat (rev=16): ame_part×5 + ori_pow×10 -> LC_bat
    #   ame_part: ame_ore -> refin(r1) -> ame_fiber -> fit(r3) -> ame_part
    #   ori_pow:  ori_ore -> shred(r0) -> ori_pow
    'LC_bat': ProductSpec(
        name='LC_bat', revenue=16, chain_depth=3,
        raw_materials={'ame_ore': 5, 'ori_ore': 10},
        machine_types={
            'refining_unit': 1, 'fitting_unit': 1,
            'shredding_unit': 1, 'packaging_unit': 1,
        },
        total_power = 10 + 10 + 10 + 20,   # 50
        critical_path_s = 3 * 2,
        terminal_recipe = ('packaging_unit', 1),
        power_battery = 'LC_bat',
    ),

    # buck_cap_B (rev=27): ferrium_bottle×10 + ground_buck_pow×10 -> buck_cap_B
    #   ferrium_bottle: ferri_ore -> refin -> ferrium -> mould(r1)×2 -> ferrium_bottle
    'buck_cap_B': ProductSpec(
        name='buck_cap_B', revenue=27, chain_depth=4,
        raw_materials={'ferri_ore': 20, 'buckflower': 10, 'sandleaf': 5},
        machine_types={
            'refining_unit': 1, 'shredding_unit': 2,
            'grinding_unit': 1, 'moulding_unit': 1, 'filling_unit': 1,
        },
        total_power = 10 + 2*10 + 20 + 10 + 20,  # 80
        critical_path_s = 4 * 2,
        terminal_recipe = ('filling_unit', 2),
        power_battery = 'SC_bat',
    ),

    # can_cit_B (rev=27): ferrium_bottle×10 + ground_citrome_pow×10 -> can_cit_B
    'can_cit_B': ProductSpec(
        name='can_cit_B', revenue=27, chain_depth=4,
        raw_materials={'ferri_ore': 20, 'citrome': 10},
        machine_types={
            'refining_unit': 1, 'shredding_unit': 2,
            'grinding_unit': 1, 'moulding_unit': 1, 'filling_unit': 1,
        },
        total_power = 10 + 2*10 + 20 + 10 + 20,  # 80
        critical_path_s = 4 * 2,
        terminal_recipe = ('filling_unit', 3),
        power_battery = 'SC_bat',
    ),
}

# ── Summarise ─────────────────────────────────────────────────────────────────
print(f"{'Product':15s} {'Rev':>5} {'Depth':>6} {'Power':>6} {'Rev/Pwr':>8} "
      f"{'Footprint':>10} {'Raw materials'}")
print("-" * 85)
for p in sorted(ALL_PRODUCTS.values(), key=lambda x: -x.revenue):
    rm  = ", ".join(f"{m}×{q}" for m, q in p.raw_materials.items())
    fp  = p.footprint_cells()
    rpp = p.revenue_per_power()
    print(f"  {p.name:13s} {p.revenue:>5} {p.chain_depth:>6} {p.total_power:>6} "
          f"{rpp:>8.3f} {fp:>10}  {rm}")

# ─── NSGA-II & FLP OPTIMISATION CONFIG (v4, standalone — every tunable knob here) ─
#!pip install deap  # Added to ensure compatibility with Colab/Jupyter
import math
import random
from collections import defaultdict, deque
from dataclasses import dataclass
from deap import base, creator, tools, algorithms
import numpy as np

@dataclass
class FLPConfig:
    # --- Multiprocessing Toggle ---
    MULTIPROCESSING: bool = True
    N_JOBS: int = -1  # -1 uses all available cores
    # --- reproducibility --------------------------------------------------
    RANDOM_SEED: int = 42          # seeds population init, crossover, mutation,
                                    # AND (deterministically, per genotype) the
                                    # ZPF disruption-recovery search below.

    # --- GA (NSGA-II) -------------------------------------------------------
    POP_SIZE: int = 300
    NGEN: int = 50
    CXPB: float = 0.8              # crossover probability
    MUTPB: float = 0.3             # mutation probability
    MAX_MACHINES: int = 100        # hard cap on machines/individual
    # (minimise build_cost, maximise terminal_rate, minimise MHC, minimise regret)
    OBJ_WEIGHTS: tuple = (-1.0, 1.0, -1.0, -1.0)

    # --- ZPF disruption zone (Four-zone Euclidean model) ---------------------
    ZPF_X: int = 22
    ZPF_Y: int = 22
    ZPF_W: int = 3
    ZPF_H: int = 3
    ZPF_R1: float = 5.0
    ZPF_R2: float = 12.0
    ZPF_ITERATIONS: int = 4

    # --- ZPF recovery search (simulated-annealing-style acceptance) ---------
    SA_INITIAL_TEMP: float = 1.0
    SA_COOLING_RATE: float = 0.85
    SA_WEIGHTS_INIT: tuple = (1.0, 1.0)   # initial (swap, shuffle) destroy-op weights
    PENALTY_PER_MOVED_MACHINE: float = 100.0
    INFEASIBLE_PENALTY: float = 1_000_000.0

    # --- feasibility fitness shaping -----------------------------------------
    # terminal_rate and regret are graded by these weighted gate ratios instead
    # of snapping to 0/1 the moment a single gate (placement, routing, power,
    # self-sustainability) is missed.
    W_PLACEMENT: float = 0.25
    W_ROUTING:   float = 0.25
    W_POWER:     float = 0.25
    W_SUSTAIN:   float = 0.25

    # --- GA genes / mutation --------------------------------------------------
    # Calibrated against derive_rate_balanced_bom() directly: machine count vs
    # rate is a step function dominated by ceil() rounding, and it was FLAT
    # across the entire old 0.005-0.02 range for every product (e.g. buck_cap_A
    # -> 65 machines at rate=0.005 AND at rate=0.1 - identical BOM either way).
    # That, combined with init_individual() only ever activating one product,
    # is why layouts stayed small: the gene ranges couldn't reach the part of
    # the search space where rate/product-count actually change the BOM.
    # 0.15-0.45 sits past that dead zone for every product's response curve.
    MIN_TERMINAL_RATE: float = 0.15
    MAX_TERMINAL_RATE: float = 0.45
    PRODUCT_ACTIVATION_PROB: float = 0.4  # per-product odds of being active at init
    MULT_INIT_MIN: float = 0.1        # initial range for recipe-multiplier genes
    MULT_INIT_MAX: float = 1.0
    MUT_RATE_SIGMA: float = 0.08       # scaled up to match the new, wider rate range
    MUT_GENE_SIGMA: float = 0.15

    # --- power / battery --------------------------------------------------------
    BATTERY_CAPACITY: int = 1100   # power supplied per Thermal Bank added by derive_bom

    # --- simulation --------------------------------------------------------------
    SIM_EQ_MAX_TICKS: int = 300    # self-sustainability tick budget (Gate 2)

    # --- base-layout macro-repair (ALNS + Tabu) ---------------------------------
    # evaluate_layout() used to run a single greedy BLF decode with no
    # repair, which silently dropped any machine that didn't fit on the
    # first pass. This closes that gap the same way the v3-architecture
    # notebook does: destroy-and-reinsert a subset of machines to reduce the
    # unplaced count, then a short Tabu polish pass to cut MHC once
    # placement/routing are complete.
    # NOTE: raising these further has sharply diminishing returns above
    # ~10 iterations — tested directly on a 158-machine BOM, routing only
    # moved from 63/115 to 67/115 going from 5 to 40 iterations. Missing
    # routes at high machine counts are predominantly a grid-congestion
    # problem (no physical space left for A* to route through), not a
    # search-depth problem, so more iterations mostly just cost more time.
    ALNS_MAX_ITERS: int = 50
    ALNS_DESTROY_PROB: float = 0.35
    TABU_MAX_ITERS: int = 20
    TABU_LIST_SIZE: int = 8

    # --- final connect-or-remove cleanup -----------------------------------------
    # After ALNS+Tabu, any machine that still isn't connected to anything gets
    # one more targeted shot at connecting (trying every port combination, not
    # just the one derive_flow_matrix assigned) before being removed outright.
    # This trades "matches the original BOM size" for "everything left is
    # actually working" -- set PRUNE_UNCONNECTABLE=False to keep the strict,
    # original behaviour (dangling unrouted flows just stay unrouted).
    PRUNE_UNCONNECTABLE: bool = False  # v5: removal deleted; only connection
    RECONNECT_MAX_ATTEMPTS: int = 12  # port combinations tried per stuck flow
    RECONNECT_MAX_PASSES: int = 6     # retry cycles — machines are never removed,
                                       # but extra passes still help route
                                       # previously-blocked flows after others clear

    # --- feasibility gate strictness -----------------------------------------
    # The v3-architecture notebook's actual evaluate_fitness (verified
    # directly in its source) never required 100% routing completeness for
    # `feasible` either -- only all_placed, power_ok, and sustain_ok. An
    # unrouted flow costs an MHC penalty instead of blocking feasibility
    # outright. That's the main reason it reports "feasible" layouts readily
    # even on complex/dense ones, and evaluate_layout now matches it by
    # default. Set this True to restore the previous, stricter requirement
    # that every single flow must route.
    REQUIRE_FULL_ROUTING: bool = False

    # --- multi-layout evaluation per individual --------------------------------
    # For every decoded chromosome, N_LAYOUT_TRIES BLF orderings are tried:
    # the first uses the evolved gene-priority vector (exploitative); the rest
    # apply Gaussian perturbations (explorative). The best result by
    # feasibility-weighted revenue is kept and cached. This reduces sensitivity
    # to BLF ordering without discarding the GA's learned priority signal.
    N_LAYOUT_TRIES: int = 5

    # --- logging ---------------------------------------------------------------
    SHOW_BLF_WARNINGS: bool = False  # print every BLF "could not place" line;
                                      # off by default (very noisy over a GA
                                      # run). Failures are still tallied in
                                      # BLF_UNPLACED_COUNT regardless.

CFG = FLPConfig()

# Seed every RNG the notebook touches, once, for reproducible end-to-end runs.
random.seed(CFG.RANDOM_SEED)
np.random.seed(CFG.RANDOM_SEED)

# Single source of truth: override the Section-1 defaults with the config knobs.
SIM_EQ_MAX_TICKS = CFG.SIM_EQ_MAX_TICKS
BLF_VERBOSE = CFG.SHOW_BLF_WARNINGS

# Back-compat aliases — later cells refer to these bare names directly.
POP_SIZE     = CFG.POP_SIZE
NGEN         = CFG.NGEN
CXPB         = CFG.CXPB
MUTPB        = CFG.MUTPB
MAX_MACHINES = CFG.MAX_MACHINES


def individual_repair_seed(individual) -> int:
    """Deterministic seed derived from an individual's genes.

    The ZPF disruption-recovery search is stochastic (destroy-operator choice,
    swap indices, SA acceptance). Without this, re-running it on the *same*
    genotype at a later point (e.g. re-checking the Pareto front after the GA
    has finished) can land on a different, possibly worse, recovery purely by
    chance, even though nothing about the individual changed. Seeding a
    private RNG from a hash of the genotype makes recovery a deterministic
    function of the genes.
    """
    key = tuple(round(v, 6) if isinstance(v, float) else v for v in individual)
    return hash((CFG.RANDOM_SEED, key)) & 0xFFFFFFFF


def _chromosome_repair_seed(chromosome) -> int:
    """Deterministic seed derived from a chromosome's own gene content (see
    individual_repair_seed above for why this matters). evaluate_layout() is
    called more than once on an identical chromosome object in the common
    case — once directly in evaluate_nsga2, and again inside zpf_recovery as
    its disruption-free baseline unless a precomputed `base` is passed in —
    so keying the seed off the gene content itself, rather than plumbing an
    rng through every caller, keeps every one of those calls reproducible
    without changing evaluate_layout's external signature.
    """
    key = tuple((g.machine_id, g.recipe_idx, g.rotation) for g in chromosome.genes)
    return hash((CFG.RANDOM_SEED, key)) & 0xFFFFFFFF


# We extract all recipes from MACHINE_CATALOGUE as (machine_id, recipe_idx)
ALL_RECIPES = []
for m_id, m_type in MACHINE_CATALOGUE.items():
    if m_type.recipes:
        for r_idx in range(len(m_type.recipes)):
            ALL_RECIPES.append((m_id, r_idx))
TARGET_PRODUCTS = [
    "buck_cap_A", "can_cit_A", "buck_cap_B", "can_cit_B",
    "HC_bat", "SC_bat", "LC_bat"
]
print("DEAP NSGA-II initialized (v5 — multi-layout, no culling, boosted params).")
print(f"Config: {CFG}")

def _chain_time(placed, routed):
    proc = {p.instance_id: (p.machine_type.recipes[p.active_recipe].process_time
           if p.active_recipe is not None and p.machine_type.recipes else 0) for p in placed}
    incoming, outgoing = defaultdict(list), defaultdict(list)
    indeg = {p.instance_id: 0 for p in placed}
    for fp, path in routed:
        if path:
            incoming[fp.dst_id].append((fp.src_id, len(path) - 1))
            outgoing[fp.src_id].append(fp.dst_id)
            indeg[fp.dst_id] += 1

    q = deque(p.instance_id for p in placed if indeg[p.instance_id] == 0)
    arrival = {}

    # Standard Kahn's topological sort
    while q:
        node = q.popleft()
        arr = proc.get(node, 0)
        if incoming[node]:
            arr += max((arrival.get(s, 0) + d * BELT_SPEED for s, d in incoming[node]), default=0)
        arrival[node] = arr

        for dst in outgoing[node]:
            indeg[dst] -= 1
            if indeg[dst] == 0:
                q.append(dst)

    # If there are cycles (like the botanical ecosystem), forcefully evaluate them
    remaining = [p.instance_id for p in placed if p.instance_id not in arrival]
    if remaining:
        for node in remaining:
            arrival[node] = proc.get(node, 0)
        # Propagate a few times to resolve loop timings
        for _ in range(min(len(remaining), 10)):
            for node in remaining:
                arr = proc.get(node, 0)
                if incoming[node]:
                    arr += max((arrival.get(s, 0) + d * BELT_SPEED for s, d in incoming[node]), default=0)
                arrival[node] = arr

    return max(arrival.values(), default=0)

def _calculate_revenue(placed, routed):
    in_nodes = defaultdict(list)
    out_nodes = defaultdict(list)
    all_nodes = set()
    path_cache = {}

    for fp, path in routed:
        in_nodes[fp.dst_id].append(fp.src_id)
        out_nodes[fp.src_id].append(fp.dst_id)
        all_nodes.update([fp.src_id, fp.dst_id])
        if path is not None:
            path_cache[(fp.src_id, fp.dst_id)] = len(path) - 1

    for pm in placed:
        all_nodes.add(pm.instance_id)

    indeg = {n: len(in_nodes[n]) for n in all_nodes}
    queue = deque(n for n in all_nodes if indeg[n] == 0)
    topo = []
    while queue:
        node = queue.popleft()
        topo.append(node)
        for dst in out_nodes[node]:
            indeg[dst] -= 1
            if indeg[dst] == 0:
                queue.append(dst)

    efficiency = {pm.instance_id: 1.0 for pm in placed}
    for node in topo:
        inputs = in_nodes[node]
        if not inputs:
            continue
        min_eff = 1.0
        for src in inputs:
            eff = efficiency.get(src, 1.0) * (1.0 if (src, node) in path_cache else 0.01)
            if eff < min_eff: min_eff = eff
        efficiency[node] = min_eff

    revenue = 0.0
    for pm in placed:
        if pm.active_recipe is not None and pm.machine_type.recipes:
            r = pm.machine_type.recipes[pm.active_recipe]
            eff = efficiency.get(pm.instance_id, 1.0)
            for out_name, out_qty in r.outputs:
                if out_name in REVENUE_TABLE:
                    ticks = max(1.0, r.process_time)  # was /2.0 -- an unexplained rate-doubling fudge factor
                    revenue += REVENUE_TABLE[out_name] * (out_qty / ticks) * eff
    return revenue

def _decode_instances(instances, fast_routing=False):
    """Shared BLF-decode-and-route helper used by evaluate_layout and both
    repair passes below, so they all measure a candidate layout identically."""
    grid = FactoryGrid()
    chromo = Chromosome([Gene(m.id, Rotation.R0, r) for m, r, _, _ in instances])
    placed = blf_decode(chromo, grid)
    flows = derive_flow_matrix(placed)
    if fast_routing:
        placed_dict = {p.instance_id: p for p in placed}
        routed = []
        for fp in flows:
            src_pm = placed_dict.get(fp.src_id)
            dst_pm = placed_dict.get(fp.dst_id)
            if src_pm and dst_pm:
                dist = abs(src_pm.x - dst_pm.x) + abs(src_pm.y - dst_pm.y)
                routed.append((fp, [None] * (dist + 1)))
    else:
        routed = route_belts(grid, {p.instance_id: p for p in placed}, flows)
    return grid, placed, flows, routed


def alns_macro_repair(sorted_instances, max_iters=None, destroy_prob=None, rng=None):
    """Destroy-and-reinsert repair that reduces the unplaced-machine count
    AND actively favours orderings that route more flows, not just ones that
    place more machines. Ported from the v3-architecture notebook (already
    fixed there: private seeded rng instead of the bare global `random`
    module). Returns (instances, is_feasible, grid, placed, flows, routed)
    where is_feasible means "fully placed and fully routed" — a
    placement/routing-only check, not the full 4-gate power/sustain
    feasibility evaluate_layout computes.
    """
    max_iters = CFG.ALNS_MAX_ITERS if max_iters is None else max_iters
    destroy_prob = CFG.ALNS_DESTROY_PROB if destroy_prob is None else destroy_prob
    rng = rng if rng is not None else random

    if not sorted_instances:
        return sorted_instances, True, FactoryGrid(), [], [], []

    best_instances = sorted_instances[:]
    best_grid, best_placed, best_fm, best_routes = _decode_instances(best_instances)
    best_paths = sum(1 for _, p in best_routes if p is not None)
    best_unplaced = len(best_instances) - len(best_placed)

    if best_unplaced == 0 and best_paths == len(best_fm):
        return best_instances, True, best_grid, best_placed, best_fm, best_routes

    for _ in range(max_iters):
        destroyed, kept = [], []
        for inst in best_instances:
            (destroyed if rng.random() < destroy_prob else kept).append(inst)
        if not destroyed:
            continue
        candidate = kept[:]
        for d_inst in destroyed:
            candidate.insert(rng.randint(0, len(candidate)), d_inst)

        cand_grid, cand_placed, cand_fm, cand_routes = _decode_instances(candidate)
        cand_paths = sum(1 for _, p in cand_routes if p is not None)
        cand_unplaced = len(candidate) - len(cand_placed)

        # Placement takes priority (unplaced machines fail the hardest gate),
        # but once placement is at least as good, ANY improvement in routed
        # paths is kept — not just when placement is *exactly* tied at its
        # best-ever value. Routing at this scale is the harder, more common
        # bottleneck, so it needs its own gradient rather than riding along
        # as a tiebreaker that rarely triggers.
        better = (cand_unplaced < best_unplaced or
                  (cand_unplaced <= best_unplaced and cand_paths > best_paths))
        if better:
            best_instances, best_unplaced, best_paths = candidate, cand_unplaced, cand_paths
            best_grid, best_placed, best_fm, best_routes = cand_grid, cand_placed, cand_fm, cand_routes

        if best_unplaced == 0 and best_paths == len(best_fm):
            return best_instances, True, best_grid, best_placed, best_fm, best_routes

    is_feasible = (best_unplaced == 0 and best_paths == len(best_fm) and len(best_fm) > 0)
    return best_instances, is_feasible, best_grid, best_placed, best_fm, best_routes


def tabu_micro_polish(sorted_instances, max_iters=None, tabu_list_size=None, rng=None):
    """MHC-improving swap search, run only once placement/routing are already
    complete. Ported from the v3-architecture notebook."""
    max_iters = CFG.TABU_MAX_ITERS if max_iters is None else max_iters
    tabu_list_size = CFG.TABU_LIST_SIZE if tabu_list_size is None else tabu_list_size
    rng = rng if rng is not None else random

    best_instances = sorted_instances[:]
    best_grid, best_placed, best_fm, best_routes = _decode_instances(best_instances)
    if len(best_instances) < 2:
        return best_instances, best_grid, best_placed, best_fm, best_routes

    best_mhc = sum(len(p) for _, p in best_routes if p is not None)
    tabu_list = []

    for _ in range(max_iters):
        idx1, idx2 = rng.randrange(len(best_instances)), rng.randrange(len(best_instances))
        if idx1 == idx2:
            continue
        swap_pair = tuple(sorted([idx1, idx2]))
        if swap_pair in tabu_list:
            continue

        candidate = best_instances[:]
        candidate[idx1], candidate[idx2] = candidate[idx2], candidate[idx1]
        cand_grid, cand_placed, cand_fm, cand_routes = _decode_instances(candidate)

        if len(cand_placed) < len(candidate):
            tabu_list.append(swap_pair); continue
        cand_paths = sum(1 for _, p in cand_routes if p is not None)
        if cand_paths < len(cand_fm):
            tabu_list.append(swap_pair); continue

        cand_mhc = sum(len(p) for _, p in cand_routes if p is not None)
        if cand_mhc < best_mhc:
            best_instances, best_mhc = candidate, cand_mhc
            best_grid, best_placed, best_fm, best_routes = cand_grid, cand_placed, cand_fm, cand_routes
            tabu_list.append(swap_pair)
            if len(tabu_list) > tabu_list_size:
                tabu_list.pop(0)

    return best_instances, best_grid, best_placed, best_fm, best_routes


def connect_or_remove_unlinked(grid, placed, flows, routed, rng=None, max_attempts=None, max_passes=None):
    """Final targeted cleanup for machines ALNS/Tabu couldn't fully connect.

    Stage 1 (connect): for every unrouted flow, retries A* across multiple
    (output-port, input-port) combinations on the SAME two machines, not
    just the one derive_flow_matrix originally assigned -- a different port
    pair often opens up a path the assigned one couldn't find, especially in
    congested layouts.

    Stage 2 (remove): any machine that STILL has zero successful connections
    afterward is removed outright -- same convention cull_unlinked_machines
    uses elsewhere in this project (main_unit and power sources exempt).
    This is a machine-level check: a machine with *some* working connections
    survives even if one of its other flows never routes -- it removes
    fully-isolated dead weight, it does not guarantee every surviving
    machine is 100% routed.

    IMPORTANT: this never calls derive_flow_matrix again. Re-deriving the
    supply/demand matching from scratch on a reduced machine set reshuffles
    ALL pairings (it's a greedy, order-dependent match), which can orphan
    machines that were working fine and cascade into removing far more than
    intended. Instead, flows touching a removed machine are simply dropped
    from the existing, already-computed flow/routed lists -- every other
    pairing is left exactly as ALNS/Tabu found it.

    Repeats a few passes since removing one machine can orphan another that
    depended on it. Returns (grid, placed, flows, routed, n_removed).
    """
    rng = rng if rng is not None else random
    max_attempts = CFG.RECONNECT_MAX_ATTEMPTS if max_attempts is None else max_attempts
    max_passes = CFG.RECONNECT_MAX_PASSES if max_passes is None else max_passes

    total_removed = 0
    current_routed = routed

    for _ in range(max_passes):
        placed_lookup = {p.instance_id: p for p in placed}

        # Stage 1: retry unrouted flows across several port combinations.
        patched_routed = []
        for fp, path in current_routed:
            # A real path is a list of (x,y) tuples. fast_routing produces
            # fake placeholder paths like [None, None, ...] — treat those
            # as unrouted so we retry with real A* routing.
            is_real_path = (path is not None and len(path) > 0
                            and path[0] is not None)
            if is_real_path:
                patched_routed.append((fp, path))
                continue
            src_pm, dst_pm = placed_lookup.get(fp.src_id), placed_lookup.get(fp.dst_id)
            found_path = None
            if src_pm and dst_pm:
                outs, ins = src_pm.output_belt_points(), dst_pm.input_belt_points()
                port_pairs = [(o, i) for o in range(len(outs)) for i in range(len(ins))]
                rng.shuffle(port_pairs)
                for oi, ii in port_pairs[:max_attempts]:
                    candidate = astar(grid, outs[oi], ins[ii])
                    if candidate and grid.place_belt(candidate, f"{fp.src_id}->{fp.dst_id}"):
                        found_path = candidate
                        break
            patched_routed.append((fp, found_path))

                                # Stage 1.5: Inject utility units for starved/blocked machines.
        # Checks EVERY placed production machine — not just ones with failed
        # routes, but also ones that derive_flow_matrix never assigned ANY
        # flow to (e.g. because another machine already satisfied demand).
        # For each such orphan, we inject a depot_unloader (for missing
        # inputs) or depot_loader (for missing outputs) and route a belt.
        has_output_check = set()
        has_input_check = set()
        # Also track which machines appear in ANY flow at all
        in_any_flow = set()
        for fp, path in patched_routed:
            in_any_flow.add(fp.src_id)
            in_any_flow.add(fp.dst_id)
            if path is not None:
                has_output_check.add(fp.src_id)
                has_input_check.add(fp.dst_id)
        
        for pm in list(placed):
            if pm.machine_type.id in ("main_unit", "stash", "depot_loader", "depot_unloader") or pm.machine_type.is_power_src:
                continue
            
            needs_input = False
            needs_output = False
            if pm.active_recipe is not None and pm.machine_type.recipes:
                if pm.active_recipe < len(pm.machine_type.recipes):
                    recipe = pm.machine_type.recipes[pm.active_recipe]
                    needs_input = len(recipe.inputs) > 0 or len(recipe.common_extra) > 0
                    needs_output = len(recipe.outputs) > 0
            
            # A machine is missing input if it needs one AND either:
            #   - it has flows but none routed as dst, OR
            #   - it has NO flows at all (derive_flow_matrix skipped it)
            missing_input = needs_input and pm.instance_id not in has_input_check
            missing_output = needs_output and pm.instance_id not in has_output_check
            
            if not missing_input and not missing_output:
                continue
            
            # Helper to place a utility unit nearby and route a belt
            def _inject_utility(util_id_str, route_from_util, _pm=pm):
                util_type = MACHINE_CATALOGUE.get(util_id_str)
                if not util_type: return False
                sw, sh = util_type.size(Rotation.R0)
                best_pos, best_dist = None, float('inf')
                cx, cy = _pm.x + _pm.w // 2, _pm.y + _pm.h // 2
                # Search in expanding radius for open space
                for dy in range(-10, 11):
                    for dx in range(-10, 11):
                        sx, sy = cx + dx, cy + dy
                        if not (0 <= sx <= grid.width - sw and 0 <= sy <= grid.height - sh): continue
                        if not grid.check_clearance(sx, sy, sw, sh, clearance=0): continue
                        dist = abs(dx) + abs(dy)
                        if dist < best_dist:
                            best_dist = dist
                            best_pos = (sx, sy)
                if best_pos:
                    sx, sy = best_pos
                    u_id = f"{util_id_str}_util_{_pm.instance_id}"
                    u_pm = PlacedMachine(machine_type=util_type, x=sx, y=sy, rotation=Rotation.R0, instance_id=u_id, active_recipe=None)
                    grid.place_machine(u_pm)
                    placed.append(u_pm)
                    
                    if route_from_util:
                        outs = u_pm.output_belt_points()
                        ins = _pm.input_belt_points()
                    else:
                        outs = _pm.output_belt_points()
                        ins = u_pm.input_belt_points()
                    routed_ok = False
                    for oi in range(len(outs)):
                        for ii in range(len(ins)):
                            if not (grid.in_bounds(*outs[oi]) and grid.is_routable(*outs[oi])): continue
                            if not (grid.in_bounds(*ins[ii]) and grid.is_routable(*ins[ii])): continue
                            candidate = astar(grid, outs[oi], ins[ii])
                            src_id = u_id if route_from_util else _pm.instance_id
                            dst_id = _pm.instance_id if route_from_util else u_id
                            if candidate and grid.place_belt(candidate, f"{src_id}->{dst_id}"):
                                fp_new = FlowPair(src_id=src_id, dst_id=dst_id, material="util_flow", intensity=1.0, src_node_idx=oi, dst_node_idx=ii)
                                patched_routed.append((fp_new, candidate))
                                routed_ok = True
                                break
                        if routed_ok: break
                    if not routed_ok:
                        grid.remove_machine(u_pm)
                        placed.remove(u_pm)
                        return False
                    return True
                return False
                
            if missing_input:
                if _inject_utility("depot_unloader", route_from_util=True):
                    has_input_check.add(pm.instance_id)
            if missing_output:
                if _inject_utility("depot_loader", route_from_util=False):
                    has_output_check.add(pm.instance_id)

        # Stage 2: STRICT enforcement. A machine must successfully connect its required inputs AND outputs.
        has_input = set()
        has_output = set()
        for fp, path in patched_routed:
            if path is not None:
                has_output.add(fp.src_id)
                has_input.add(fp.dst_id)

        # v5 — No machine removal: only connect, never cull.
        # Machines that remain unrouted after max_passes are kept in place;
        # missing connections incur an MHC penalty during fitness evaluation
        # instead of being excised from the layout. This preserves the full BOM
        # across every generation and avoids shrinking machine counts mid-run.
        current_routed = patched_routed   # carry best connection state into next pass

    flows = [fp for fp, _ in current_routed]
    return grid, placed, flows, current_routed, total_removed


def evaluate_layout(chromosome, rng=None, repair=False, alns_iters=None, tabu_iters=None, fast_routing=False):
    # Reconstruct an ALNS-compatible instance list straight from the
    # chromosome's genes, in their existing (priority-sorted) order — ALNS
    # only ever reads the machine type and recipe index out of each tuple,
    # so the placeholder priority/orig_idx fields here are never read back.
    instances = [(MACHINE_CATALOGUE[g.machine_id], g.recipe_idx, 0.0, i)
                 for i, g in enumerate(chromosome.genes)]

    # Seeded deterministically from the chromosome's own gene content (see
    # _chromosome_repair_seed): makes repair a pure function of the layout,
    # so calling evaluate_layout more than once on an identical chromosome
    # always reproduces the same repair instead of drifting across calls.
    rng = rng if rng is not None else random.Random(_chromosome_repair_seed(chromosome))

    # Previously a single un-repaired blf_decode() — anything that didn't
    # fit on the first greedy pass was just dropped, with nothing retrying
    # to rescue it. ALNS actively destroys-and-reinserts to close that gap,
    # then Tabu polishes MHC once placement/routing are complete.
    if repair:
        alns_iters = alns_iters or CFG.ALNS_MAX_ITERS
        tabu_iters = tabu_iters or CFG.TABU_MAX_ITERS
        repaired_instances, is_feasible, grid, placed, flows, routed = alns_macro_repair(
            instances, max_iters=alns_iters, destroy_prob=CFG.ALNS_DESTROY_PROB, rng=rng)
        if is_feasible:
            repaired_instances, grid, placed, flows, routed = tabu_micro_polish(
                repaired_instances, max_iters=tabu_iters, tabu_list_size=CFG.TABU_LIST_SIZE, rng=rng)
    else:
        grid, placed, flows, routed = _decode_instances(instances, fast_routing=fast_routing)

    # all_placed tracks raw ALNS/BLF placement success -- did every gene make
    # it onto the grid at all -- BEFORE any deliberate pruning below. That
    # stays a hard requirement: it's what ALNS is specifically fighting for.
    all_placed = len(placed) == len(chromosome.genes)

    # Final cleanup: anything ALNS placed but never got connected to
    # anything gets one more targeted reconnect attempt, then removed if
    # that still fails. This can only IMPROVE routing/power/sustain (fewer,
    # better-connected machines) at the cost of building less than the
    # original gene count -- tracked explicitly via machines_removed rather
    # than silently changing what "feasible" means.
    machines_removed = 0
    if True:  # Always run cleanup to inject utility depots for starved machines
        grid, placed, flows, routed, machines_removed = connect_or_remove_unlinked(
            grid, placed, flows, routed, rng=rng, max_passes=10 if repair else None)

    paths_found = sum(path is not None for _, path in routed)

    # MHC: routed flows count normally. An UNROUTED flow is NOT ignored --
    # it costs a distance-based penalty (2x Manhattan distance between the
    # two machines, or a flat grid.width+grid.height if either machine is
    # somehow missing) instead. This mirrors the v3-architecture notebook's
    # actual evaluate_fitness exactly, and matters a lot: it's what gives
    # the GA a real gradient to minimise unrouted flows even now that
    # routing completeness is no longer a hard feasibility gate (below) --
    # without it, an unrouted flow would be free, and nothing would push
    # the search toward closing the gap.
    placed_lookup = {p.instance_id: p for p in placed}
    mhc = 0.0
    for fp, path in routed:
        if path is not None:
            mhc += fp.intensity * (len(path) - 1)
        else:
            src_pm, dst_pm = placed_lookup.get(fp.src_id), placed_lookup.get(fp.dst_id)
            if src_pm and dst_pm:
                dist = (abs(src_pm.x + src_pm.w // 2 - dst_pm.x - dst_pm.w // 2) +
                        abs(src_pm.y + src_pm.h // 2 - dst_pm.y - dst_pm.h // 2))
                mhc += fp.intensity * dist * 2
            else:
                mhc += fp.intensity * (GRID_W + GRID_H)

    build_cost = sum(sum(q for _, q in p.machine_type.build_cost) for p in placed)
    demand = sum(p.machine_type.power_cost for p in placed)
    output = 0
    for p in placed:
        if p.machine_type.id == "ther_bank" and p.active_recipe is not None:
            output += sum(q for m, q in p.machine_type.recipes[p.active_recipe].outputs if m == "power")

    power_ok = output > demand
    chain_time = _chain_time(placed, routed)
    sustain_ok = chain_time <= SIM_EQ_MAX_TICKS

    # Feasibility now matches what the v3-architecture notebook's
    # evaluate_fitness ACTUALLY checks (verified directly in its source):
    # `feasible = power_ok and sustain_ok and all_placed` -- routing
    # completeness was never part of its gate either. Unrouted flows are
    # costed via the MHC penalty above instead of blocking feasibility
    # outright, which is exactly why v3 reports "feasible" layouts readily
    # even when routing isn't 100% complete. Set CFG.REQUIRE_FULL_ROUTING
    # to restore the previous, stricter bar this notebook used before.
    feasible = all_placed and power_ok and sustain_ok
    if CFG.REQUIRE_FULL_ROUTING:
        feasible = feasible and paths_found == len(flows)

    revenue = _calculate_revenue(placed, routed)
    return dict(grid=grid, placed=placed, flows=flows, routed=routed, mhc=mhc,
                build_cost=build_cost, power_ok=power_ok, chain_time=chain_time,
                feasible=feasible, paths_found=paths_found, flows_total=len(flows),
                demand=demand, output=output, all_placed=all_placed, revenue=revenue,
                machines_removed=machines_removed)




print("alns_macro_repair() and tabu_micro_polish() defined; evaluate_layout() now repairs before scoring.")


# ─── ZPF DISRUPTION MODEL + RECOVERY -- applied ONLY after layout creation ──────
class ZPF:
    """Four-zone Euclidean disruption model from Thesis Chapter 3."""
    def __init__(self, x, y, w, h, r1=5.0, r2=12.0):
        self.x, self.y, self.w, self.h, self.r1, self.r2 = x, y, w, h, r1, r2
    def distance(self, x, y):
        dx = max(self.x - x, 0, x - (self.x + self.w - 1))
        dy = max(self.y - y, 0, y - (self.y + self.h - 1))
        return math.hypot(dx, dy)
    def zone(self, x, y):
        d = self.distance(x, y)
        return "unusable" if d == 0 else "flexible" if d <= self.r1 else "penalty" if d <= self.r2 else "stable"
    def machine_zone(self, pm):
        if any(self.zone(x, y) == "unusable" for x, y in pm.cells()): return "unusable"
        return self.zone(pm.x + pm.w // 2, pm.y + pm.h // 2)


def _recover_layout(stable, disruption, order):
    """Rebuild a grid from a fixed `stable` set (kept at their original
    coordinates, disruption rectangle permanently blocked) plus any machines
    in `order` re-inserted via BLF on whatever room is left. An EMPTY order
    renders "just after the blast, before any recovery attempt". Factored
    out of zpf_recovery()'s old `recover()` closure so bombed_state() can
    share the exact same placement rule -- bombed and recovered states
    can't disagree about what "destroyed" means.
    """
    grid = FactoryGrid()
    for y in range(disruption.y, disruption.y + disruption.h):
        for x in range(disruption.x, disruption.x + disruption.w):
            if grid.in_bounds(x, y): grid.grid[y][x] = (TileState.BLOCKED, None)
    placed = []
    for pm in stable:
        if grid.place_machine(pm): placed.append(pm)
    for old in order:
        found = None
        for y in range(grid.height - old.h + 1):
            for x in range(grid.width - old.w + 1):
                candidate = type(old)(old.machine_type, x, y, old.rotation,
                                      old.instance_id, old.active_recipe)
                if grid.place_machine(candidate):
                    found = candidate; break
            if found: break
        if found: placed.append(found)
    flows = derive_flow_matrix(placed)
    routed = route_belts(grid, {p.instance_id: p for p in placed}, flows)
    mhc = sum(f.intensity * (len(p) - 1) for f, p in routed if p)
    demand = sum(p.machine_type.power_cost for p in placed)
    output = sum(sum(q for m, q in p.machine_type.recipes[p.active_recipe].outputs if m == "power")
                 for p in placed if p.machine_type.id == "ther_bank" and p.active_recipe is not None)
    power_ok = output > demand
    paths_found = sum(p is not None for _, p in routed)
    chain_time = _chain_time(placed, routed)
    sustain_ok = chain_time <= SIM_EQ_MAX_TICKS
    # ── V6: Post-recovery reconnection pass ──
    grid, placed, flows, routed = post_recovery_reconnect(grid, placed, flows, routed, rng=rng)
    # Recalculate ALL metrics after reconnection
    mhc = sum(f.intensity * (len(p) - 1) for f, p in routed if p)
    demand = sum(p.machine_type.power_cost for p in placed)
    output = sum(sum(q for m, q in p.machine_type.recipes[p.active_recipe].outputs if m == "power")
                 for p in placed if p.machine_type.id == "ther_bank" and p.active_recipe is not None)
    power_ok = output > demand
    paths_found = sum(p is not None for _, p in routed)
    chain_time = _chain_time(placed, routed)
    sustain_ok = chain_time <= SIM_EQ_MAX_TICKS
    revenue = _calculate_revenue(placed, routed)
    return dict(grid=grid, placed=placed, flows=flows, routed=routed, mhc=mhc,
                power_ok=power_ok, chain_time=chain_time,
                paths_found=paths_found, flows_total=len(flows),
                demand=demand, output=output,
                feasible=len(placed) == len(stable) + len(order) and
                paths_found == len(flows) and power_ok and sustain_ok,
                revenue=revenue)


def bombed_state(base, disruption):
    """The layout immediately after a ZPF disruption, before any recovery
    attempt: stable machines untouched, everything the blast reached
    destroyed outright, ground zero permanently blocked. Uses the exact
    same _recover_layout() rule zpf_recovery() uses (called with an empty
    order), so "destroyed" can't quietly mean something different here than
    it does during recovery. Adds n_destroyed/n_stable onto the result.
    """
    stable = [p for p in base["placed"] if disruption.machine_zone(p) == "stable"]
    result = _recover_layout(stable, disruption, [])
    result["n_destroyed"] = len(base["placed"]) - len(stable)
    result["n_stable"] = len(stable)
    return result



def post_recovery_reconnect(grid, placed, flows, routed, rng=None):
    """Post-recovery reconnection pass: ensures every surviving machine
    is connected after ZPF bomb recovery. Prioritizes machines that produce
    unique or widely-used materials in the current layout's active recipes.
    
    Steps:
      1. Identify all machines missing input/output connections
      2. Score each by material uniqueness & usage in the layout
      3. Reconnect in priority order via depot injection
      4. Return updated (grid, placed, flows, routed) with recalculated metrics
    """
    rng = rng if rng is not None else random

    # ── Step 1: Identify connected vs unconnected machines ──
    has_input = set()
    has_output = set()
    for fp, path in routed:
        if path is not None:
            has_output.add(fp.src_id)
            has_input.add(fp.dst_id)

    unconnected = []
    for pm in placed:
        if pm.machine_type.id in ("main_unit", "stash", "depot_loader", "depot_unloader") or pm.machine_type.is_power_src:
            continue
        needs_input = False
        needs_output = False
        if pm.active_recipe is not None and pm.machine_type.recipes:
            if pm.active_recipe < len(pm.machine_type.recipes):
                recipe = pm.machine_type.recipes[pm.active_recipe]
                needs_input = len(recipe.inputs) > 0 or len(recipe.common_extra) > 0
                needs_output = len(recipe.outputs) > 0
        missing_in = needs_input and pm.instance_id not in has_input
        missing_out = needs_output and pm.instance_id not in has_output
        if missing_in or missing_out:
            unconnected.append((pm, missing_in, missing_out))

    if not unconnected:
        return grid, placed, flows, routed

    # ── Step 2: Score machines by material priority ──
    # Build maps of what each machine produces/consumes in this layout
    layout_producers = {}   # material -> list of instance_ids that produce it
    layout_consumers = {}   # material -> count of how many active recipes consume it
    for pm in placed:
        if pm.active_recipe is None or not pm.machine_type.recipes:
            continue
        if pm.active_recipe >= len(pm.machine_type.recipes):
            continue
        recipe = pm.machine_type.recipes[pm.active_recipe]
        for mat, qty in recipe.outputs:
            if mat not in layout_producers:
                layout_producers[mat] = []
            layout_producers[mat].append(pm.instance_id)
        for mat, qty in recipe.inputs:
            layout_consumers[mat] = layout_consumers.get(mat, 0) + 1
        for mat, qty in recipe.common_extra:
            layout_consumers[mat] = layout_consumers.get(mat, 0) + 1

    def _priority_score(pm):
        score = 0.0
        if pm.active_recipe is None or not pm.machine_type.recipes:
            return 0.0
        if pm.active_recipe >= len(pm.machine_type.recipes):
            return 0.0
        recipe = pm.machine_type.recipes[pm.active_recipe]

        for mat, qty in recipe.outputs:
            # Unique producer bonus: this is the ONLY machine making this material
            producers = layout_producers.get(mat, [])
            if len(producers) == 1 and producers[0] == pm.instance_id:
                score += 100.0
            # Widely-used bonus: how many active recipes in the layout consume this
            score += layout_consumers.get(mat, 0)
            # Revenue bonus
            if mat in REVENUE_TABLE:
                score += REVENUE_TABLE[mat]
        return score

    # Sort by priority (highest first)
    unconnected.sort(key=lambda t: _priority_score(t[0]), reverse=True)

    # ── Step 3: Reconnect via utility depot injection ──
    for pm, missing_in, missing_out in unconnected:
        def _inject_utility(util_id_str, route_from_util, _pm=pm):
            util_type = MACHINE_CATALOGUE.get(util_id_str)
            if not util_type:
                return False
            sw, sh = util_type.size(Rotation.R0)
            best_pos, best_dist = None, float("inf")
            cx, cy = _pm.x + _pm.w // 2, _pm.y + _pm.h // 2
            for dy in range(-10, 11):
                for dx in range(-10, 11):
                    sx, sy = cx + dx, cy + dy
                    if not (0 <= sx <= grid.width - sw and 0 <= sy <= grid.height - sh):
                        continue
                    if not grid.check_clearance(sx, sy, sw, sh, clearance=0):
                        continue
                    dist = abs(dx) + abs(dy)
                    if dist < best_dist:
                        best_dist = dist
                        best_pos = (sx, sy)
            if best_pos:
                sx, sy = best_pos
                u_id = f"{util_id_str}_recov_{_pm.instance_id}"
                u_pm = PlacedMachine(
                    machine_type=util_type, x=sx, y=sy,
                    rotation=Rotation.R0, instance_id=u_id,
                    active_recipe=None,
                )
                grid.place_machine(u_pm)
                placed.append(u_pm)
                if route_from_util:
                    outs = u_pm.output_belt_points()
                    ins = _pm.input_belt_points()
                else:
                    outs = _pm.output_belt_points()
                    ins = u_pm.input_belt_points()
                routed_ok = False
                for oi in range(len(outs)):
                    for ii in range(len(ins)):
                        if not (grid.in_bounds(*outs[oi]) and grid.is_routable(*outs[oi])):
                            continue
                        if not (grid.in_bounds(*ins[ii]) and grid.is_routable(*ins[ii])):
                            continue
                        candidate = astar(grid, outs[oi], ins[ii])
                        src_id = u_id if route_from_util else _pm.instance_id
                        dst_id = _pm.instance_id if route_from_util else u_id
                        if candidate and grid.place_belt(candidate, f"{src_id}->{dst_id}"):
                            fp_new = FlowPair(
                                src_id=src_id, dst_id=dst_id,
                                material="recovery_flow", intensity=1.0,
                                src_node_idx=oi, dst_node_idx=ii,
                            )
                            routed.append((fp_new, candidate))
                            routed_ok = True
                            break
                    if routed_ok:
                        break
                if not routed_ok:
                    grid.remove_machine(u_pm)
                    placed.remove(u_pm)
                    return False
                return True
            return False

        if missing_in:
            _inject_utility("depot_unloader", route_from_util=True)
        if missing_out:
            _inject_utility("depot_loader", route_from_util=False)

    # Update flows list
    flows = [fp for fp, _ in routed]
    return grid, placed, flows, routed


def zpf_recovery(chromosome, disruption, iterations=None, rng=None, base=None):
    """ALNS-style recovery restricted to flexible/penalty machines.

    iterations defaults to CFG.ZPF_ITERATIONS. rng lets callers pass a seeded
    random.Random for reproducible recovery (see individual_repair_seed);
    falls back to the global `random` module if not supplied. `base` lets a
    caller that has already computed evaluate_layout(chromosome) pass that
    result straight in -- evaluate_layout now runs ALNS+Tabu repair, so
    recomputing it here from scratch would silently repeat that same
    (no-longer-cheap) repair a second time on the identical chromosome.
    """
    iterations = CFG.ZPF_ITERATIONS if iterations is None else iterations
    rng = rng if rng is not None else random

    if base is None:
        base = evaluate_layout(chromosome)
    movable = [p for p in base["placed"] if disruption.machine_zone(p) != "stable"]
    stable = [p for p in base["placed"] if disruption.machine_zone(p) == "stable"]
    if not movable: return base, 0.0

    best, best_cost = base, math.inf
    order = movable[:]
    temperature = CFG.SA_INITIAL_TEMP
    weights = list(CFG.SA_WEIGHTS_INIT)
    for _ in range(iterations):
        candidate = order[:]
        candidate_count = len(candidate)
        if candidate_count < 2:
            # A one-machine recovery has no valid exchange neighbourhood.
            # Evaluate it directly instead of sampling an impossible pair.
            result = _recover_layout(stable, disruption, candidate)
            moved_penalty = sum(5.0 * disruption.distance(p.x + p.w/2, p.y + p.h/2) for p in result["placed"] if disruption.machine_zone(p) == "penalty")
            best = result
            best_cost = result["mhc"] + moved_penalty + \
                        (0 if result["feasible"] else CFG.INFEASIBLE_PENALTY)
            break
        if rng.random() < weights[0] / sum(weights):
            # Draw two distinct positions without random.sample(); remains
            # valid for every candidate_count >= 2.
            a = rng.randrange(candidate_count)
            b = rng.randrange(candidate_count - 1)
            if b >= a:
                b += 1
            candidate[a], candidate[b] = candidate[b], candidate[a]
        else:
            rng.shuffle(candidate)
        result = _recover_layout(stable, disruption, candidate)
        # Penalty machines are read off the RECOVERED positions
        # (result["placed"]), not the pre-shuffle `candidate` list -- those
        # objects' coordinates never change.
        moved_penalty = sum(5.0 * disruption.distance(p.x + p.w/2, p.y + p.h/2) for p in result["placed"] if disruption.machine_zone(p) == "penalty")
        cost = result["mhc"] + moved_penalty + \
               (0 if result["feasible"] else CFG.INFEASIBLE_PENALTY)
        if cost < best_cost or rng.random() < math.exp((best_cost - cost) / max(temperature, .01)):
            improved = cost < best_cost
            order, best, best_cost = candidate, result, cost
            weights[0 if improved else 1] += 1
        temperature *= CFG.SA_COOLING_RATE
    return best, best_cost

print("ZPF disruption model, bombed_state(), and zpf_recovery() defined")
print("(applied only in Phase 3, after layout creation is fully complete).")

# ─── V4 FITNESS EVALUATION ───────────────────────────────────────────────────────
def derive_rate_balanced_bom(product_rates, multipliers):
    """Incremental backward expansion; shared demand is never discarded."""
    if not hasattr(multipliers, "get"):
        multipliers = dict(zip(ALL_RECIPES, multipliers))
    demand, expanded, required = defaultdict(float), defaultdict(float), defaultdict(int)
    for name, rate in zip(TARGET_PRODUCTS, product_rates):
        if rate > 0: demand[name] += rate
    queue = deque(demand)
    while queue:
        item = queue.popleft()
        delta = demand[item] - expanded[item]
        if delta <= 1e-9: continue
        producers = [(mid, i, r, q) for mid, mt in MACHINE_CATALOGUE.items() for i, r in enumerate(mt.recipes)
                     for out, q in r.outputs if out == item]
        if not producers: expanded[item] = demand[item]; continue
        mid, idx, recipe, out = max(producers, key=lambda p: multipliers.get((p[0], p[1]), .5))
        target_count = math.ceil(demand[item] / (out / recipe.process_time))
        increment = max(0, target_count - required[(mid, idx)])
        required[(mid, idx)] += increment; expanded[item] = demand[item]
        for material, qty in recipe.inputs + recipe.common_extra:
            demand[material] += increment * qty / recipe.process_time
            queue.append(material)
    instances = [(MACHINE_CATALOGUE["main_unit"], None)]
    for (mid, idx), count in required.items():
        instances.extend((MACHINE_CATALOGUE[mid], idx) for _ in range(count))
    power = sum(m.power_cost for m, _ in instances)
    if power:
        instances.extend((MACHINE_CATALOGUE["ther_bank"], 2)
                          for _ in range(math.floor(power / CFG.BATTERY_CAPACITY) + 1))
    return instances

def _feasibility_ratio(res, chromosome_len):
    placement_ratio = min(1.0, len(res["placed"]) / max(1, chromosome_len))
    route_ratio = min(1.0, (res["paths_found"] / res["flows_total"]) if res["flows_total"] else 1.0)
    power_ratio = min(1.0, res["output"] / res["demand"]) if res["demand"] > 0 else 1.0
    ct = res["chain_time"]
    sustain_ratio = (min(1.0, SIM_EQ_MAX_TICKS / ct) if 0 < ct < math.inf else (1.0 if ct == 0 else 0.0))
    w = (CFG.W_PLACEMENT + CFG.W_ROUTING + CFG.W_POWER + CFG.W_SUSTAIN) or 1.0
    return (CFG.W_PLACEMENT * placement_ratio + CFG.W_ROUTING * route_ratio +
            CFG.W_POWER * power_ratio + CFG.W_SUSTAIN * sustain_ratio) / w


def evaluate_nsga2(individual):
    n_mix, n_rec = len(TARGET_PRODUCTS), len(ALL_RECIPES)
    rates, mult = individual[:n_mix], individual[n_mix:n_mix + n_rec]
    instances = derive_rate_balanced_bom(rates, dict(zip(ALL_RECIPES, mult)))

    raw_terminal_rate = sum(max(0.0, rate) * REVENUE_TABLE[name] for name, rate in zip(TARGET_PRODUCTS, rates)
                             if name in REVENUE_TABLE)

    if len(instances) > MAX_MACHINES:
        # Graded over-budget penalty — replaces a flat (1e9, 0.0, 1e9, 1e9)
        # for ANY overage, which made a BOM 1 machine over the cap and one
        # 1000 machines over the cap look identical to the optimizer: both a
        # dead end, so there was no gradient pulling the population back
        # DOWN toward the boundary from above, only pressure to stay well
        # clear of it entirely. Scaling the penalty with the overage, and
        # still reporting a (discounted) terminal_rate instead of zero, lets
        # NSGA-II tell "barely over, ambitious" apart from "wildly oversized"
        # and approach MAX_MACHINES as a real boundary rather than a cliff to
        # avoid.
        overage_ratio = (len(instances) - MAX_MACHINES) / MAX_MACHINES
        penalty = 1e5 * (1.0 + overage_ratio)
        return (penalty, raw_terminal_rate * 0.1, penalty, penalty)

    # ── Multi-layout evaluation: best of N_LAYOUT_TRIES orderings ─────────
    # First try uses the evolved gene-priority vector (exploitative).
    # Subsequent tries apply Gaussian perturbations to explore alternative
    # BLF orderings without discarding the learned priority signal.
    # The best result by feasibility-weighted revenue is kept and cached.
    priorities  = individual[n_mix + n_rec:]
    total_genes = len(instances)
    best_result = None
    best_score  = -1.0

    for _try in range(getattr(CFG, "N_LAYOUT_TRIES", 5)):
        if _try == 0:
            # Exploitative: use the evolved priority vector
            ordered = sorted(enumerate(instances),
                             key=lambda e: priorities[e[0]] if e[0] < len(priorities) else 0,
                             reverse=True)
        else:
            # Explorative: perturb priorities with Gaussian noise
            perturbed = [p + random.gauss(0, 0.15) for p in priorities]
            ordered   = sorted(enumerate(instances),
                               key=lambda e: perturbed[e[0]] if e[0] < len(perturbed) else 0,
                               reverse=True)

        chromo = Chromosome([Gene(m.id, Rotation.R0, r) for _, (m, r) in ordered])
        result = evaluate_layout(chromo, repair=False, fast_routing=True)
        feas   = _feasibility_ratio(result, total_genes)
        score  = result["revenue"] * feas

        if score > best_score or (abs(score - best_score) < 1e-9 and (best_result is None or result["mhc"] < best_result["mhc"])):
            best_score  = score
            best_result = result

    result        = best_result
    main_feas     = _feasibility_ratio(result, total_genes)
    terminal_rate = result["revenue"] * main_feas   # feasibility-weighted (v4 signal preserved)
    regret        = 0.0

    # (Removed _flp_cache to prevent joblib Pickling OOM bombs)

    return (result["build_cost"], terminal_rate, result["mhc"], regret)

print("derive_rate_balanced_bom() and evaluate_nsga2() defined (v5, multi-layout per individual, no culling).")


# ─── GA CONFIGURATION ───────────────────────────────────────────────────────────
if "FitnessV4" in creator.__dict__: del creator.FitnessV4
if "IndividualV4" in creator.__dict__: del creator.IndividualV4
creator.create("FitnessV4", base.Fitness, weights=CFG.OBJ_WEIGHTS)
creator.create("IndividualV4", list, fitness=creator.FitnessV4)
toolbox = base.Toolbox()

# --- Multiprocessing Toggle ---
if getattr(CFG, 'MULTIPROCESSING', True):
    from joblib import Parallel, delayed
    def joblib_map(func, iterable):
        return Parallel(n_jobs=getattr(CFG, 'N_JOBS', -1), backend="loky")(delayed(func)(item) for item in iterable)
    toolbox.register("map", joblib_map)
    print(f"DEAP Multiprocessing ENABLED (Cores: {getattr(CFG, 'N_JOBS', 'All')})")
else:
    toolbox.register("map", map)
    print("DEAP Multiprocessing DISABLED")

n_mix, n_rec = len(TARGET_PRODUCTS), len(ALL_RECIPES)

def init_individual():
    # Terminal rates are per tick. Activate a random SUBSET of products
    # (each independently, at CFG.PRODUCT_ACTIVATION_PROB) instead of always
    # exactly one — the single-product-only initialization was the main
    # reason layouts stayed small and simple: with pwx previously never
    # touching this segment either (see below), a lineage's product mix was
    # frozen at whatever init_individual() drew for its entire evolutionary
    # history. At least one product is guaranteed active so the BOM is never
    # trivially empty.
    rates = [0.0] * n_mix
    active = [i for i in range(n_mix) if random.random() < CFG.PRODUCT_ACTIVATION_PROB]
    if not active:
        active = [random.randrange(n_mix)]
    for i in active:
        rates[i] = random.uniform(CFG.MIN_TERMINAL_RATE, CFG.MAX_TERMINAL_RATE)
    return creator.IndividualV4(rates +
        [random.uniform(CFG.MULT_INIT_MIN, CFG.MULT_INIT_MAX) for _ in range(n_rec)] +
        [random.random() for _ in range(MAX_MACHINES)])

def pwx(a, b):
    # Uniform crossover across the WHOLE individual — product-mix rates and
    # recipe multipliers included, not just the layout-priority tail. Before,
    # "what to build and how much" could only change within a lineage via
    # slow Gaussian mutation; two individuals with different, independently-
    # successful product combinations could never recombine into a denser
    # offspring that builds both.
    for i in range(len(a) - 1):
        if random.random() < .5: a[i], b[i] = b[i], a[i]
    return a, b

def custom_mutate(ind):
    for i in range(n_mix):
        ind[i] = min(CFG.MAX_TERMINAL_RATE, max(0., ind[i] + random.gauss(0, CFG.MUT_RATE_SIGMA)))
    for i in range(n_mix, len(ind)):
        ind[i] = min(1., max(0., ind[i] + random.gauss(0, CFG.MUT_GENE_SIGMA)))
    return ind,

toolbox.register("individual", init_individual)
toolbox.register("population", tools.initRepeat, list, toolbox.individual)
toolbox.register("evaluate", evaluate_nsga2)
toolbox.register("mate", pwx)
toolbox.register("mutate", custom_mutate)
toolbox.register("select", tools.selNSGA2)
print("GA configured: FitnessV4 weights", CFG.OBJ_WEIGHTS)

# ─── RUN NSGA-II ────────────────────────────────────────────────────────────────
def run_nsga2():
    print(f"Starting NSGA-II: Pop={POP_SIZE}, Gen={NGEN}...")
    pop = toolbox.population(n=POP_SIZE)

    fitnesses = list(toolbox.map(toolbox.evaluate, pop))
    for ind, fit in zip(pop, fitnesses):
        ind.fitness.values = fit

    history = {'gen': [], 'best_cost': [], 'best_rate': [], 'best_mhc': [],
               'best_regret': [], 'avg_rate': []}

    stagnation_counter = 0
    best_rate_ever = -1.0

    for gen in range(1, NGEN + 1):
        offspring = algorithms.varAnd(pop, toolbox, cxpb=CXPB, mutpb=MUTPB)
        fits = list(toolbox.map(toolbox.evaluate, offspring))
        for ind, fit in zip(offspring, fits):
            ind.fitness.values = fit

        pop = toolbox.select(pop + offspring, k=POP_SIZE)
        best = max(pop, key=lambda x: x.fitness.values[1])
        current_best_rate = best.fitness.values[1]

        if current_best_rate > best_rate_ever + 1e-4:
            best_rate_ever = current_best_rate
            stagnation_counter = 0
        else:
            stagnation_counter += 1

        if stagnation_counter >= 5:
            print(f"  [AIS] Stagnation detected (5 gens). Triggering Clonal Hypermutation!")
            num_elites = max(5, int(POP_SIZE * 0.05))
            elites = tools.selNSGA2(pop, k=num_elites)

            clones = [toolbox.clone(ind) for ind in elites for _ in range(3)]
            for clone in clones:
                toolbox.mutate(clone)
                toolbox.mutate(clone)
                toolbox.mutate(clone)
                del clone.fitness.values

            clone_fits = list(map(toolbox.evaluate, clones))
            for ind, fit in zip(clones, clone_fits):
                ind.fitness.values = fit

            ranked_pop = tools.selNSGA2(pop, k=len(pop))
            num_replace = len(clones)
            pop = ranked_pop[:-num_replace] + clones

            best = max(pop, key=lambda x: x.fitness.values[1])
            stagnation_counter = 0

        avg_rate = sum(x.fitness.values[1] for x in pop) / len(pop)

        history['gen'].append(gen)
        history['best_cost'].append(best.fitness.values[0])
        history['best_rate'].append(best.fitness.values[1])
        history['best_mhc'].append(best.fitness.values[2])
        history['best_regret'].append(best.fitness.values[3])
        history['avg_rate'].append(avg_rate)

        print(f"Gen {gen:2d}: Best Rate={best.fitness.values[1]:.4f}, "
              f"Cost={best.fitness.values[0]:.0f}, MHC={best.fitness.values[2]:.0f}, "
              f"Regret={best.fitness.values[3]:.4f}  |  Avg Rate={avg_rate:.4f}")

    print("NSGA-II Complete!")
    return pop, history

final_pop, conv_history = run_nsga2()
pareto_front = tools.selNSGA2(final_pop, k=len(final_pop))


# ─── NSGA-II CONVERGENCE & PARETO FRONT VISUALIZATION ───────────────────────────
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

fig, axes = plt.subplots(2, 2, figsize=(14, 10))
fig.suptitle('NSGA-II Optimization Dashboard (v4)', fontsize=14, fontweight='bold')

# 1. Terminal-rate convergence (already folds the graded feasibility score in
#    — see evaluate_nsga2 — so this is the closest v4 analogue of the old
#    "Feasibility Convergence" + "Revenue Convergence" panels combined)
ax = axes[0, 0]
ax.plot(conv_history['gen'], conv_history['best_rate'], 'o-',
        color='#2980B9', linewidth=2, markersize=4, label='Best')
ax.plot(conv_history['gen'], conv_history['avg_rate'], 's--',
        color='#95A5A6', linewidth=1.5, markersize=3, label='Avg')
ax.set_xlabel('Generation')
ax.set_ylabel('Terminal Rate (feasibility-weighted)')
ax.set_title('Terminal Rate Convergence')
ax.legend(fontsize=8)
ax.grid(alpha=0.3)

# 2. Build cost convergence
ax = axes[0, 1]
ax.plot(conv_history['gen'], conv_history['best_cost'], 'o-',
        color='#8E44AD', linewidth=2, markersize=4)
ax.set_xlabel('Generation')
ax.set_ylabel('Build Cost')
ax.set_title('Build Cost Convergence (Best)')
ax.grid(alpha=0.3)

# 3. MHC convergence
ax = axes[1, 0]
ax.plot(conv_history['gen'], conv_history['best_mhc'], 'o-',
        color='#E67E22', linewidth=2, markersize=4)
ax.set_xlabel('Generation')
ax.set_ylabel('Material Handling Cost')
ax.set_title('MHC Convergence (Best)')
ax.grid(alpha=0.3)

# 4. Pareto front scatter (Terminal Rate vs MHC, coloured by graded
#    feasibility read from each individual's cached evaluation)
ax = axes[1, 1]
rate_vals = [ind.fitness.values[1] for ind in pareto_front]
mhc_vals  = [ind.fitness.values[2] for ind in pareto_front]
feas_vals = [getattr(ind, '_flp_cache', {}).get('main_feas', 0.0) for ind in pareto_front]
sc = ax.scatter(rate_vals, mhc_vals, c=feas_vals, cmap='RdYlGn',
                s=60, edgecolors='#2C3E50', linewidth=0.8, vmin=0, vmax=1)
plt.colorbar(sc, ax=ax, label='Feasibility (graded)')
ax.set_xlabel('Terminal Rate')
ax.set_ylabel('MHC (belt cells)')
ax.set_title('Pareto Front (coloured by feasibility)')
ax.grid(alpha=0.3)

plt.tight_layout()
plt.savefig('v4_nsga2_dashboard.png', dpi=150, bbox_inches='tight')
plt.show()
print("Saved: v4_nsga2_dashboard.png")
# ─── PHASE 2: RIGOROUS FEASIBILITY POLISH ───────────────────────────────────────
from types import SimpleNamespace
import traceback

print("=" * 70)
print("PHASE 2: Rigorous Feasibility Polish — Re-evaluating top candidates")
print("=" * 70)

# From NSGA, pick top 20 by REVENUE first (fitness.values[1])
candidates = sorted(pareto_front, key=lambda x: x.fitness.values[1], reverse=True)[:20]
refined = []

for i, ind in enumerate(candidates):
    n_mix, n_rec = len(TARGET_PRODUCTS), len(ALL_RECIPES)
    rates, mult = ind[:n_mix], ind[n_mix:n_mix + n_rec]
    instances = derive_rate_balanced_bom(rates, dict(zip(ALL_RECIPES, mult)))
    priorities = ind[n_mix + n_rec:]
    ordered = sorted(enumerate(instances), key=lambda e: priorities[e[0]] if e[0] < len(priorities) else 0, reverse=True)
    chromo = Chromosome([Gene(m.id, Rotation.R0, r) for _, (m, r) in ordered])
    
    # Heavy Repair (REQUIRE_FULL_ROUTING is False here — GA explored freely)
    # v5: explicitly trigger ALNS+Tabu repair during polish
    result = evaluate_layout(chromo, repair=True,
                             alns_iters=CFG.ALNS_MAX_ITERS,
                             tabu_iters=CFG.TABU_MAX_ITERS)
    
    total_genes = len(instances)
    main_feas = _feasibility_ratio(result, total_genes)
    
    # --- UNCONDITIONAL STRICT ROUTING POLISH ---
    print(f"  [!] Candidate {i+1} initial feasibility: {main_feas:.1%}. Forcing strict routing polish...")
    grid, placed = result["grid"], result["placed"]
    flows, routed = result["flows"], result["routed"]
    
    grid, placed, flows, routed, culled = connect_or_remove_unlinked(
        grid, placed, flows, routed, max_attempts=100, max_passes=10
    )
    
    mhc, paths_found = 0.0, 0
    for fp, path in routed:
        if path is not None:
            paths_found += 1
            mhc += len(path) - 1
            
    demand = sum(pm.machine_type.power_cost for pm in placed)
    output = 0
    for pm in placed:
        if pm.machine_type.id == "ther_bank" and pm.active_recipe is not None:
            output += sum(q for m, q in pm.machine_type.recipes[pm.active_recipe].outputs if m == "power")
    power_ok = (output >= demand)
    chain_time = _chain_time(placed, routed)
    sustain_ok = (0 < chain_time <= SIM_EQ_MAX_TICKS)
    all_placed = (len(placed) == len(instances))
    
    # AFTER connection polish: strict feasibility check
    # Routing completeness NOW matters — if belts are still missing after
    # 100 A* attempts and 10 cleanup passes, the layout is not feasible
    feasible = all_placed and power_ok and sustain_ok and (paths_found == len(flows))
        
    revenue = _calculate_revenue(placed, routed)
    result.update({
        "grid": grid, "placed": placed, "flows": flows, "routed": routed,
        "mhc": mhc, 
        "build_cost": sum(sum(q for _, q in pm.machine_type.build_cost) for pm in placed),
        "power_ok": power_ok, "chain_time": chain_time, "feasible": feasible,
        "paths_found": paths_found, "flows_total": len(flows),
        "demand": demand, "output": output, "all_placed": all_placed,
        "revenue": revenue, "machines_removed": result["machines_removed"] + culled
    })
    main_feas = _feasibility_ratio(result, total_genes)
    # --------------------------------------------------------
    
    terminal_rate = result["revenue"] * main_feas
    refined.append((ind, result, terminal_rate, total_genes, chromo, main_feas))
    
    feas_tag = "FEASIBLE" if result["feasible"] else "PARTIAL"
    print(f"  Candidate {i+1:2d}: Rate={terminal_rate:.4f}, Cost={result['build_cost']:.0f}, MHC={result['mhc']:.0f}, Feasibility={main_feas:.1%} [{feas_tag}]")

# AFTER polish: sort by feasible FIRST, then by terminal_rate
# Feasibility is now strict (requires full routing), so only truly complete
# factories get the "FEASIBLE" badge. Among those, highest profit wins.
refined.sort(key=lambda x: (x[1]["feasible"], x[2]), reverse=True)
n_feasible = sum(1 for r in refined if r[1]["feasible"])
print(f"\nRefinement complete: {n_feasible}/{len(candidates)} candidates are fully feasible.")

def _to_fitness_result(res, terminal_rate, total_genes):
    return SimpleNamespace(
        mhc=res["mhc"], revenue=terminal_rate,
        power_feasible=res["power_ok"], chain_time=res["chain_time"],
        paths_found=res["paths_found"], paths_total=res["flows_total"],
        feasible=res["feasible"],
    )
# ─── PHASE 3: ZPF DISASTER SIMULATION ───────────────────────────────────────────
print("\n" + "=" * 70)
print("PHASE 3: ZPF Disaster Simulation (before bombing / after bombing / after recovery)")
print("=" * 70)

top_10 = refined[:10]
zpf_disruption = ZPF(CFG.ZPF_X, CFG.ZPF_Y, CFG.ZPF_W, CFG.ZPF_H, CFG.ZPF_R1, CFG.ZPF_R2)

for idx, (ind, result, terminal_rate, total_genes, chromo, main_feas) in enumerate(top_10):
    label = f"Top {idx+1}" if result["feasible"] else f"Best Partial {idx+1}"
    print(f"\n{'='*60}\n  {label}  (Rate={terminal_rate:.2f}, Feasibility={main_feas:.1%})\n{'='*60}")

    before = result
    print(f"  Before bombing : {len(before['placed'])} machines, feasible={before['feasible']}")

    after_bombing = bombed_state(before, zpf_disruption)
    print(f"  After bombing  : {len(after_bombing['placed'])} machines "
          f"({after_bombing['n_destroyed']} destroyed, {after_bombing['n_stable']} stable), "
          f"feasible={after_bombing['feasible']}")

    rng = random.Random(individual_repair_seed(ind))
    after_recovery, recovery_cost = zpf_recovery(chromo, zpf_disruption, base=before, rng=rng)
    print(f"  After recovery : {len(after_recovery['placed'])} machines, "
          f"cost={recovery_cost:.1f}, feasible={after_recovery['feasible']}")

    for state_label, res in [("prebomb", before), ("bombed", after_bombing), ("recovered", after_recovery)]:
        path = f"v4_layout_{label.lower().replace(' ', '_')}_{state_label}.png"
        title = f"{label} -- {state_label} (Rate: {terminal_rate:.2f}, Feas: {main_feas:.1%})"
        try:
            plot_layout(res["grid"], _to_fitness_result(res, res.get("revenue", 0.0), total_genes), res["flows"],
                        save_path=path, zpf_zone=zpf_disruption, title_str=title)
        except Exception:
            print(f"  [plot error for {state_label}]")
            import traceback
            traceback.print_exc()


import traceback
try:
    c = Chromosome([Gene('steel_furnace', Rotation.R0, 0.5)])
    res = evaluate_layout(c, repair=True, alns_iters=1, tabu_iters=1)
    print("evaluate_layout return type:", type(res))
    if isinstance(res, dict):
        print("keys:", res.keys())
    else:
        print("res:", res)
except Exception as e:
    traceback.print_exc()
