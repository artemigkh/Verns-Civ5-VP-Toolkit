# Verns Civ 5 VP Toolkit
A collection of utilities for Civ 5 Vox Populi Utilities / Stats / Visualizations

## Database Util
`/util` contains `db_export.py`, which must be run to generate CSV files used by many other scripts. This is a one-time step that should be re-run whenever the database is updated.

## Promotion Tree Generator
`/promotion_tree` contains `generate_promotion_tree.py`, which leverages graphviz to generate a visual representation of the promotion tree for each unit class.

## Autoplay Framework

The framework for running repeated iterations of games across many computers and collecting the logs into a single directory, `/data` by default. This is the source of the data used for all analyses and visualizations.

## Analysis and Visualizations
`/analysis` contains a variety of scripts for analyzing the data and generating visualizations. These are mostly written in R, but some Python visualizations also exist with some overlap.
