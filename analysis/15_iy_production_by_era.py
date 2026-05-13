"""Histograms of instant-yield production values faceted by Era.

Loads all part-*.csv files from
``data/MP_AUTOPLAY_VP_5_2_3/intermediate_csvs/instant_yields/``,
concatenates them, filters for rows where ``iy_production > 0``, and
produces a grid of histograms — one panel per Era.

Output: ``analysis/output/iy_production_by_era.png``
"""

from __future__ import annotations

import glob
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

ANALYSIS_DIR = Path(__file__).resolve().parent
REPO_ROOT = ANALYSIS_DIR.parent
IY_DIR = REPO_ROOT / "data" / "MP_AUTOPLAY_VP_5_2_3" / "intermediate_csvs" / "instant_yields"
OUTPUT_PATH = ANALYSIS_DIR / "output" / "iy_production_by_era.png"
CSV_OUT_DIR = ANALYSIS_DIR / "output" / "iy_production_by_era"

# ---------------------------------------------------------------------------
# Load data
# ---------------------------------------------------------------------------

csv_files = sorted(IY_DIR.glob("part-*.csv"))
if not csv_files:
    raise FileNotFoundError(f"No part-*.csv files found in {IY_DIR}")

df = pd.concat([pd.read_csv(f) for f in csv_files], ignore_index=True)

# Filter to positive production events for Border Growth only
df_prod = df[(df["iy_production"] > 0) & (df["reason"] == "Border Growth")].copy()

# Era labels
ERA_LABELS = {
    1: "Era 1: Ancient",
    2: "Era 2: Classical",
    3: "Era 3: Medieval",
    4: "Era 4: Renaissance",
    5: "Era 5: Industrial",
    6: "Era 6: Modern",
    7: "Era 7: Atomic",
    8: "Era 8: Information",
    9: "Era 9: Spaceship",
    10: "Era 10: Future",
}

eras = sorted(df_prod["era"].unique())
n_eras = len(eras)

# ---------------------------------------------------------------------------
# Plot
# ---------------------------------------------------------------------------

ncols = 3
nrows = -(-n_eras // ncols)  # ceiling division

fig, axes = plt.subplots(nrows, ncols, figsize=(5 * ncols, 4 * nrows), sharex=False, sharey=False)
axes_flat = axes.flatten()

for i, era in enumerate(eras):
    ax = axes_flat[i]
    subset = df_prod[df_prod["era"] == era]["iy_production"]
    ax.hist(subset, bins=30, color="steelblue", edgecolor="white", linewidth=0.4)
    ax.set_title(ERA_LABELS.get(era, f"Era {era}"), fontsize=11)
    ax.set_xlabel("iy_production")
    ax.set_ylabel("Count")
    ax.spines[["top", "right"]].set_visible(False)

# Hide any unused panels
for j in range(i + 1, len(axes_flat)):
    axes_flat[j].set_visible(False)

fig.suptitle("Instant-Yield Production (Border Growth) — Distribution by Era\n(rows with iy_production > 0)", fontsize=13, y=1.01)
fig.tight_layout()

OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
fig.savefig(OUTPUT_PATH, dpi=150, bbox_inches="tight")
plt.close(fig)

# Write per-era CSVs
CSV_OUT_DIR.mkdir(parents=True, exist_ok=True)
for era in eras:
    label = ERA_LABELS.get(era, f"era_{era}").split(": ", 1)[-1].lower().replace(" ", "_")
    era_csv = CSV_OUT_DIR / f"era_{era:02d}_{label}.csv"
    df_prod[df_prod["era"] == era].to_csv(era_csv, index=False)
    print(f"Saved CSV → {era_csv}")

print(f"Saved plot → {OUTPUT_PATH}")
print(f"Total rows with iy_production > 0: {len(df_prod):,}")
print(f"Eras present: {eras}")
