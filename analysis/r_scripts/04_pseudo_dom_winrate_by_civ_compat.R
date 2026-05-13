# 04_compat: same as 04_pseudo_dom_winrate_by_civ.R but reads from an
# alternate dataset (defaults to the WSL log-processor output) and writes
# under output/r_plots/compat/{light,dark}/. See common_compat.R for env
# knobs.
source("r_scripts/common_compat.R")
source("r_scripts/04_pseudo_dom_winrate_by_civ.R", chdir = FALSE,
       local = FALSE)
