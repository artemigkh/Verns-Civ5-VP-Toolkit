# 07: Reformation beliefs frequency + win rate.
source("r_scripts/common.R")

rel <- load_religion_data()

reformation_picks <- rel$choices %>% filter(type == "religion_reformed")
reformation_stats <- belief_pick_stats(rel$choices, "religion_reformed",
                                       rel$categories)

# --- Win/loss stacked bars -----------------------------------------------
reformation_plot_a <- plot_belief_winloss_stack(
    reformation_stats,
    title = "Reformation Beliefs - Frequency And Performance",
    theme_fn = theme_report,
    text_color = "grey25", bar_outline = "grey25"
)
save_plot(reformation_plot_a, "07a_reformation_beliefs_freq_perf",
          width = 13, height = max(6, 0.48 * nrow(reformation_stats) + 3))

reformation_plot_b <- plot_belief_winloss_stack(
    reformation_stats,
    title = "Reformation Beliefs - Frequency And Performance",
    theme_fn = theme_report_dark,
    text_color = IPSUM_VP_DARK_FG, bar_outline = IPSUM_VP_DARK_BG
)
save_plot_dark(reformation_plot_b, "07b_reformation_beliefs_freq_perf",
               width = 13, height = max(6, 0.48 * nrow(reformation_stats) + 3))

# --- Turn-picked ridgeline variants --------------------------------------
ridge_height <- max(6, 0.55 * nrow(reformation_stats) + 3)

reformation_ridge_a <- plot_belief_turn_ridge(
    reformation_picks, reformation_stats,
    title = "Reformation Beliefs - Turn Picked Distribution",
    theme_fn = theme_report, bg = IPSUM_VP_BG,
    viridis_opt = "viridis", vline_color = "white"
)
save_plot(reformation_ridge_a, "07a_reformation_beliefs_turn_ridgeline",
          width = 13, height = ridge_height)

reformation_ridge_b <- plot_belief_turn_ridge(
    reformation_picks, reformation_stats,
    title = "Reformation Beliefs - Turn Picked Distribution",
    theme_fn = theme_report_dark, bg = IPSUM_VP_DARK_BG,
    viridis_opt = "inferno", begin = 0.05, end = 0.95,
    vline_color = IPSUM_VP_DARK_BG
)
save_plot_dark(reformation_ridge_b, "07b_reformation_beliefs_turn_ridgeline",
               width = 13, height = ridge_height)
