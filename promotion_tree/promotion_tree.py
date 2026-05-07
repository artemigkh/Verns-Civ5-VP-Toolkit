"""Generate promotion tree diagrams (per UnitCombat type) from the Civ5 VP debug DB.

Converted from PromotionTreeScratch.ipynb. Reads the Civ5 / Vox Populi
Localization-Merged.db and Civ5DebugDatabase.db that the game writes to the
user's "My Games" cache folder, and emits:

    * <UNITCOMBAT_TYPE>.png/.gv            - "trimmed" promotion trees (no orphan uniques)
    * <UNITCOMBAT_TYPE>_FULL.png/.gv       - full promotion trees including uniques
    * promotion_trees_trimmed.zip          - bundle of selected trimmed PNGs
    * promotion_trees_full.zip             - bundle of selected _FULL PNGs

Run with `python promotion_tree.py` from inside the promotion_tree/ folder, or
pass --output-dir to write outputs elsewhere. The script requires `dot` from
Graphviz to be on PATH so the python `graphviz` package can render PNGs.
"""

from __future__ import annotations

import argparse
import os
import re
import sqlite3
import zipfile
from pathlib import Path

import graphviz
import pandas as pd

DEFAULT_CIV5_CACHE = Path(
    os.path.expandvars(r"%USERPROFILE%\Documents\My Games\Sid Meier's Civilization 5\cache")
)

# Unit combat classes to bundle into the zip archives.
ZIP_UNIT_COMBAT_TYPES = [
    "UNITCOMBAT_ARCHER",
    "UNITCOMBAT_ARMOR",
    "UNITCOMBAT_BOMBER",
    "UNITCOMBAT_CARRIER",
    "UNITCOMBAT_FIGHTER",
    "UNITCOMBAT_GUN",
    "UNITCOMBAT_MELEE",
    "UNITCOMBAT_MOUNTED",
    "UNITCOMBAT_NAVALMELEE",
    "UNITCOMBAT_NAVALRANGED",
    "UNITCOMBAT_RECON",
    "UNITCOMBAT_SUBMARINE",
    "UNITCOMBAT_SIEGE",
]

PREREQ_COLS = [
    "PromotionPrereq",
    "PromotionPrereqOr1",
    "PromotionPrereqOr2",
    "PromotionPrereqOr3",
    "PromotionPrereqOr4",
    "PromotionPrereqOr5",
    "PromotionPrereqOr6",
    "PromotionPrereqOr7",
    "PromotionPrereqOr8",
    "PromotionPrereqOr9",
]


def load_text_lut(loc_db: Path) -> dict[str, str]:
    with sqlite3.connect(loc_db) as cnx:
        df = pd.read_sql_query("select Tag, Text from Language_en_US", cnx)
    return dict(zip(df.Tag, df.Text))


def replace_text_with_values(text: str, txt_lut: dict[str, str]) -> str:
    for key, value in txt_lut.items():
        placeholder = "{" + key + "}"
        if placeholder in text:
            text = text.replace(placeholder, value)
    return text


class PromotionTree:
    def __init__(self, combat_type: str, txt_lut: dict[str, str], show_uniques: bool = False):
        self.combat_type = combat_type
        self.txt_lut = txt_lut
        self.show_uniques = show_uniques
        self.nodes: dict[str, "PromotionTreeNode"] = {}

    def add_node_from_row(self, promotion_row):
        node = PromotionTreeNode(self, promotion_row)
        self.nodes[node.promotion_type] = node

    def render_tree(self) -> graphviz.Digraph:
        dot = graphviz.Digraph(comment=self.combat_type)
        dot.attr("node", shape="rectangle")
        dot.attr("graph", rankdir="LR")
        dot.attr("graph", dpi="300")
        dot.attr("graph", labelloc="t")
        dot.attr("graph", label=self.txt_lut.get("TXT_KEY_" + self.combat_type, self.combat_type))

        if not self.show_uniques:
            for promotion in list(self.nodes.keys()):
                if not self.nodes[promotion].tree_contains_root_prereq():
                    del self.nodes[promotion]

        for promotion, node in self.nodes.items():
            if self._has_connection(promotion):
                if node.mounted_only or node.needs_air_sweep:
                    dot.attr("node", color="red")
                elif node.min_range_required >= 2 or node.needs_intercept_range:
                    dot.attr("node", color="blue")
                else:
                    dot.attr("node", color="black")
                dot.node(name=promotion, label=node.render_label())

        edges = []
        for promotion, node in self.nodes.items():
            for requirement in node.requirements:
                if requirement in self.nodes and promotion in self.nodes:
                    edges.append((requirement, promotion))
        dot.edges(edges)
        return dot

    def _has_connection(self, promotion: str) -> bool:
        if self.nodes[promotion].requirements:
            return True
        for _, node in self.nodes.items():
            for requirement in node.requirements:
                if promotion == requirement:
                    return True
        return False


class PromotionTreeNode:
    def __init__(self, promotion_tree: PromotionTree, promotion_row):
        self.promotion_tree = promotion_tree
        self.promotion_type = promotion_row["PromotionType"]
        # Some pandas/sqlite versions return NaN (not None) for NULL text columns,
        # so use pd.notna to drop both. Empty strings are also dropped.
        self.requirements = [
            promotion_row[col]
            for col in PREREQ_COLS
            if pd.notna(promotion_row[col]) and promotion_row[col] != ""
        ]
        self.description_key = promotion_row["Description"]
        self.caption_key = promotion_row["Help"]
        self.mounted_only = promotion_row["MountedOnly"]
        self.min_range_required = promotion_row["MinimumRangeRequired"]
        self.needs_intercept_range = (
            (promotion_row["InterceptChanceChange"] or 0) > 0
            or (promotion_row["NumInterceptionChange"] or 0) > 0
            or (promotion_row["InterceptionCombatModifier"] or 0) > 0
        )
        self.needs_air_sweep = (promotion_row["AirSweepCombatModifier"] or 0) > 0

    def render_label(self) -> str:
        txt_lut = self.promotion_tree.txt_lut
        raw_caption = txt_lut.get(self.caption_key, "")
        caption = re.sub(r"[\(\[].*?[\)\]]", "", replace_text_with_values(raw_caption, txt_lut))
        caption = re.sub(r"\s\s+", " ", caption)
        caption = caption.replace(".", ".<br/>")
        title = txt_lut.get(self.description_key, self.promotion_type)
        return (
            f'<<FONT POINT-SIZE="12">{title}</FONT><br/>'
            f'<FONT POINT-SIZE="6">{caption}</FONT>>'
        )

    def tree_contains_root_prereq(self) -> bool:
        if not self.requirements:
            return True
        for parent in self.requirements:
            if parent in self.promotion_tree.nodes:
                if self.promotion_tree.nodes[parent].tree_contains_root_prereq():
                    return True
        return False


def render_combat_trees(
    cnx: sqlite3.Connection, txt_lut: dict[str, str], output_dir: Path
) -> None:
    unit_combat_infos_df = pd.read_sql_query("select * from UnitCombatInfos", cnx)
    promos_for_combat = pd.read_sql_query(
        "select * from UnitPromotions_UnitCombats", cnx
    )
    promotions_df = pd.read_sql_query("select * from UnitPromotions", cnx)

    output_dir.mkdir(parents=True, exist_ok=True)

    for current_combat_type in unit_combat_infos_df["Type"]:
        avail = promos_for_combat[promos_for_combat["UnitCombatType"] == current_combat_type]
        avail = avail.merge(
            promotions_df, left_on=["PromotionType"], right_on=["Type"], how="inner"
        )

        # Trimmed: only player-choosable, non-tech-locked promotions
        trimmed = avail[(avail["CannotBeChosen"] == 0) & (avail["TechPrereq"].isnull())]

        for label, df in (("", trimmed), ("_FULL", avail)):
            tree = PromotionTree(current_combat_type, txt_lut, show_uniques=bool(label))
            for _, row in df.iterrows():
                tree.add_node_from_row(row)
            dot = tree.render_tree()
            out_base = output_dir / f"{current_combat_type}{label}"
            try:
                dot.render(filename=str(out_base), format="png", cleanup=False)
                print(f"Rendered {out_base}.png")
            except graphviz.backend.execute.ExecutableNotFound:
                # No graphviz binary on PATH - still emit the .gv source file
                out_base.with_suffix(".gv").write_text(dot.source, encoding="utf-8")
                print(f"Graphviz `dot` not found; wrote source only: {out_base}.gv")


def build_zip_archives(output_dir: Path) -> None:
    """Bundle selected combat-class PNGs into trimmed/full zip archives."""

    bundles = {
        "promotion_trees_trimmed.zip": [(ct, ct + ".png") for ct in ZIP_UNIT_COMBAT_TYPES],
        "promotion_trees_full.zip": [
            (ct + "_FULL", ct + "_FULL.png") for ct in ZIP_UNIT_COMBAT_TYPES
        ],
    }

    for zip_name, members in bundles.items():
        zip_path = output_dir / zip_name
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            missing = []
            for _stem, filename in members:
                src = output_dir / filename
                if src.exists():
                    zf.write(src, arcname=filename)
                else:
                    missing.append(filename)
        print(
            f"Wrote {zip_path} "
            f"({len(members) - len(missing)}/{len(members)} files"
            + (f", missing: {', '.join(missing)}" if missing else "")
            + ")"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--civ5-cache-dir",
        type=Path,
        default=DEFAULT_CIV5_CACHE,
        help="Path to Civ5 cache folder containing the .db files.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(__file__).parent / "output",
        help="Directory to write generated images and CSVs into.",
    )
    args = parser.parse_args()

    loc_db = args.civ5_cache_dir / "Localization-Merged.db"
    debug_db = args.civ5_cache_dir / "Civ5DebugDatabase.db"
    for p in (loc_db, debug_db):
        if not p.exists():
            raise SystemExit(f"Required Civ5 cache DB not found: {p}")

    args.output_dir.mkdir(parents=True, exist_ok=True)

    txt_lut = load_text_lut(loc_db)
    with sqlite3.connect(debug_db) as cnx:
        render_combat_trees(cnx, txt_lut, args.output_dir)

    build_zip_archives(args.output_dir)


if __name__ == "__main__":
    main()
