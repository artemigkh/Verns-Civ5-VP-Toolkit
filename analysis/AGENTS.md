# Instructions for AI agents working in `analysis/`

When generating or modifying R visualizations:

1. **Verify the output visually.** After making or changing a graph, open the
   produced PNG (under `analysis/output/r_plots/`) and confirm it looks
   correct — labels in the right place, axes sensible, colors readable,
   no overlaps or empty panels — before declaring the task done.
2. **Wire new R scripts into `run_all.bat`.** Whenever you add a new R
   script that produces a graph, append it to the `SCRIPTS=` list in
   [r_scripts/run_all.bat](r_scripts/run_all.bat) (or to the per-script
   loop) so it runs as part of the regular rebuild. Keep the list in
   numeric/lexical order matching the filename prefix.
3. Add any new outputs to the `.gitignore` file if they are not already covered, to avoid accidentally
   committing large binary files or generated outputs.