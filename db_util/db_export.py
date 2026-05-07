"""Extract reference CSVs from the Civ5 / Vox Populi cache databases.

Reads ``Localization-Merged.db`` and ``Civ5DebugDatabase.db`` from the user's
"My Games" Civ5 cache folder and emits the small lookup CSVs used by the R
visualization scripts and the analysis notebooks:

    * wonder_eras.csv      - wonder name -> era
    * civ_colors.csv       - civ -> primary RGB color
    * civ_bg_colors.csv    - civ -> secondary RGB color
    * civ_flavors.csv      - civ -> per-flavor pivot + leader personality
    * beliefs.csv          - religion belief metadata

Run with ``python db_util/db_export.py`` from the repository root, or pass
``--output-dir`` to write outputs elsewhere.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
from pathlib import Path

import pandas as pd

DEFAULT_CIV5_CACHE = Path(
    os.path.expandvars(r"%USERPROFILE%\Documents\My Games\Sid Meier's Civilization 5\cache")
)

CIV_TAG_TO_TEXT_MAP = {
    "CIVILIZATION_AMERICA": "America",
    "CIVILIZATION_ARABIA": "Arabia",
    "CIVILIZATION_AZTEC": "The Aztecs",
    "CIVILIZATION_CHINA": "China",
    "CIVILIZATION_EGYPT": "Egypt",
    "CIVILIZATION_ENGLAND": "England",
    "CIVILIZATION_FRANCE": "France",
    "CIVILIZATION_GERMANY": "Germany",
    "CIVILIZATION_GREECE": "Greece",
    "CIVILIZATION_INDIA": "India",
    "CIVILIZATION_IROQUOIS": "The Iroquois",
    "CIVILIZATION_JAPAN": "Japan",
    "CIVILIZATION_OTTOMAN": "The Ottomans",
    "CIVILIZATION_PERSIA": "Persia",
    "CIVILIZATION_ROME": "Rome",
    "CIVILIZATION_RUSSIA": "Russia",
    "CIVILIZATION_SIAM": "Siam",
    "CIVILIZATION_SONGHAI": "Songhai",
    "CIVILIZATION_MINOR": "City State",
    "CIVILIZATION_BARBARIAN": "Barbarians",
    "CIVILIZATION_MONGOL": "Mongolia",
    "CIVILIZATION_INCA": "The Inca",
    "CIVILIZATION_SPAIN": "Spain",
    "CIVILIZATION_POLYNESIA": "Polynesia",
    "CIVILIZATION_DENMARK": "Denmark",
    "CIVILIZATION_KOREA": "Korea",
    "CIVILIZATION_BABYLON": "Babylon",
    "CIVILIZATION_AUSTRIA": "Austria",
    "CIVILIZATION_BYZANTIUM": "Byzantium",
    "CIVILIZATION_CARTHAGE": "Carthage",
    "CIVILIZATION_CELTS": "The Celts",
    "CIVILIZATION_ETHIOPIA": "Ethiopia",
    "CIVILIZATION_HUNS": "The Huns",
    "CIVILIZATION_MAYA": "The Maya",
    "CIVILIZATION_NETHERLANDS": "The Netherlands",
    "CIVILIZATION_SWEDEN": "Sweden",
    "CIVILIZATION_ASSYRIA": "Assyria",
    "CIVILIZATION_BRAZIL": "Brazil",
    "CIVILIZATION_INDONESIA": "Indonesia",
    "CIVILIZATION_MOROCCO": "Morocco",
    "CIVILIZATION_POLAND": "Poland",
    "CIVILIZATION_PORTUGAL": "Portugal",
    "CIVILIZATION_SHOSHONE": "The Shoshone",
    "CIVILIZATION_VENICE": "Venice",
    "CIVILIZATION_ZULU": "The Zulus",
}


def load_text_lut(loc_db: Path) -> dict[str, str]:
    with sqlite3.connect(loc_db) as cnx:
        df = pd.read_sql_query("select Tag, Text from Language_en_US", cnx)
    return dict(zip(df.Tag, df.Text))


def export_wonder_eras(
    cnx: sqlite3.Connection, txt_lut: dict[str, str], out_path: Path
) -> None:
    wonders_df = pd.read_sql_query(
        """
        select bc.DefaultBuilding, b.Description, b.Type, b.PrereqTech, t.Era
        from BuildingClasses bc, Buildings b, Technologies t
        where bc.MaxGlobalInstances = 1
          and bc.DefaultBuilding = b.type
          and b.PrereqTech = t.Type
        """,
        cnx,
    )
    wonders_df["Name"] = wonders_df["Description"].map(txt_lut)
    wonders_df["Era"] = wonders_df["Era"].map(lambda s: s[4:].title())
    wonders_df[["Name", "Era"]].to_csv(out_path, index=False)
    print(f"Wrote {out_path} ({len(wonders_df)} wonders)")


def export_civ_colors(cnx: sqlite3.Connection, out_path: Path) -> None:
    df = pd.read_sql_query(
        """
        SELECT
            Civilizations.Type,
            Colors.Red * 255 AS red,
            Colors.Green * 255 AS green,
            Colors.Blue * 255 AS blue
        FROM
            Civilizations, PlayerColors, Colors
        WHERE
            Civilizations.DefaultPlayerColor = PlayerColors.Type AND
            PlayerColors.PrimaryColor = Colors.Type
        """,
        cnx,
    )
    df["civ"] = df["Type"].map(CIV_TAG_TO_TEXT_MAP)
    df = df.drop(columns=["Type"]).round()
    df.to_csv(out_path)
    print(f"Wrote {out_path} ({len(df)} civs)")


def export_civ_bg_colors(cnx: sqlite3.Connection, out_path: Path) -> None:
    df = pd.read_sql_query(
        """
        SELECT
            Civilizations.Type,
            Colors.Red * 255 AS red,
            Colors.Green * 255 AS green,
            Colors.Blue * 255 AS blue
        FROM
            Civilizations, PlayerColors, Colors
        WHERE
            Civilizations.DefaultPlayerColor = PlayerColors.Type AND
            PlayerColors.SecondaryColor = Colors.Type
        """,
        cnx,
    )
    df["civ"] = df["Type"].map(CIV_TAG_TO_TEXT_MAP)
    df = df.drop(columns=["Type"])
    df.to_csv(out_path)
    print(f"Wrote {out_path} ({len(df)} civs)")


def export_civ_flavors(cnx: sqlite3.Connection, out_path: Path) -> None:
    civ_flavors_df = pd.read_sql_query(
        """
        SELECT
            CivilizationType,
            FlavorType,
            Flavor
        FROM Leader_Flavors, Civilization_Leaders
        WHERE Leader_Flavors.LeaderType = Civilization_Leaders.LeaderheadType
        AND CivilizationType != "CIVILIZATION_MINOR"
        AND CivilizationType != "CIVILIZATION_BARBARIAN"

        UNION

        SELECT
            CivilizationType,
            MajorCivApproachType AS FlavorType,
            Bias AS Flavor
        FROM Leader_MajorCivApproachBiases, Civilization_Leaders
        WHERE Leader_MajorCivApproachBiases.LeaderType = Civilization_Leaders.LeaderheadType
        AND CivilizationType != "CIVILIZATION_MINOR"
        AND CivilizationType != "CIVILIZATION_BARBARIAN"
        """,
        cnx,
    )
    civ_flavors_df["civ"] = civ_flavors_df["CivilizationType"].map(CIV_TAG_TO_TEXT_MAP)
    # Collapse duplicate (civ, FlavorType) rows -- a civ can have multiple
    # leaders mapped, but we just need one Flavor value per (civ, type).
    civ_flavors_df = (
        civ_flavors_df.groupby(["civ", "FlavorType"], as_index=False)["Flavor"].first()
    )

    leaders_cols = {
        row[1]
        for row in cnx.execute("PRAGMA table_info(Leaders)").fetchall()
    }
    optional_cols = [
        c
        for c in ("Personality", "PrimaryVictoryPursuit", "SecondaryVictoryPursuit")
        if c in leaders_cols
    ]
    select_cols = ["Type", "CivilizationType", "Description", *optional_cols]
    leader_personality_df = pd.read_sql_query(
        f"""
        SELECT {', '.join(select_cols)}
        FROM Leaders, Civilization_Leaders
        WHERE Leaders.Type = Civilization_Leaders.LeaderheadType
        AND CivilizationType != "CIVILIZATION_MINOR"
        AND CivilizationType != "CIVILIZATION_BARBARIAN"
        """,
        cnx,
    )
    leader_personality_df["civ"] = leader_personality_df["CivilizationType"].map(
        CIV_TAG_TO_TEXT_MAP
    )
    if "Personality" in leader_personality_df.columns:
        leader_personality_df["Personality"] = leader_personality_df["Personality"].str.replace(
            "PERSONALITY_", "", regex=False
        )
    for col in ("PrimaryVictoryPursuit", "SecondaryVictoryPursuit"):
        if col in leader_personality_df.columns:
            leader_personality_df[col] = leader_personality_df[col].str.replace(
                "VICTORY_PURSUIT_", "", regex=False
            )

    pivoted = pd.pivot_table(
        civ_flavors_df, index=["civ"], columns=["FlavorType"], values="Flavor"
    ).merge(leader_personality_df, on="civ", how="left")
    pivoted.to_csv(out_path)
    print(f"Wrote {out_path} ({len(pivoted)} civs)")


def export_beliefs(
    cnx: sqlite3.Connection, txt_lut: dict[str, str], out_path: Path
) -> None:
    df = pd.read_sql_query(
        """
        SELECT
            ID,
            ShortDescription,
            Pantheon,
            Founder,
            Follower,
            Enhancer,
            Reformation
        FROM Beliefs
        """,
        cnx,
    )
    df["ShortDescription"] = df["ShortDescription"].map(lambda k: txt_lut.get(k, k))
    df.to_csv(out_path, index=False)
    print(f"Wrote {out_path} ({len(df)} beliefs)")


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
        default=Path(__file__).parent / "out",
        help="Directory to write generated CSVs into.",
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
        export_wonder_eras(cnx, txt_lut, args.output_dir / "wonder_eras.csv")
        export_civ_colors(cnx, args.output_dir / "civ_colors.csv")
        export_civ_bg_colors(cnx, args.output_dir / "civ_bg_colors.csv")
        export_civ_flavors(cnx, args.output_dir / "civ_flavors.csv")
        export_beliefs(cnx, txt_lut, args.output_dir / "beliefs.csv")


if __name__ == "__main__":
    main()
