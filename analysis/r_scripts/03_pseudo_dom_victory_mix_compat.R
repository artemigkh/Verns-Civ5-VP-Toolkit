# 03_compat: same as 03_pseudo_dom_victory_mix.R but reads from an
# alternate dataset (defaults to the WSL log-processor output) and writes
# under output/r_plots/compat/{light,dark}/. See common_compat.R for env
# knobs.
source("r_scripts/common_compat.R")
source("r_scripts/03_pseudo_dom_victory_mix.R", chdir = FALSE, local = FALSE)
