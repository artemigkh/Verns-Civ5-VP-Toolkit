# 06: Pantheon belief frequency + win rate.
source("r_scripts/common.R")

rel <- load_religion_data()

pantheon_picks <- rel$choices %>% filter(type == "pantheon")
pantheon_stats <- belief_pick_stats(rel$choices, "pantheon", rel$categories)

CAPTION <- default_caption()

# --- Win/loss stacked bars -----------------------------------------------
pantheon_plot_a <- plot_belief_winloss_stack(
    pantheon_stats,
    title = "Pantheon Pick Frequency And Performance",
    caption = CAPTION,
    theme_fn = theme_report,
    text_color = "grey25", bar_outline = "grey25"
) + caption_theme("a")
save_plot(pantheon_plot_a, "06a_pantheon_freq_perf",
          width = 13, height = max(6, 0.48 * nrow(pantheon_stats) + 3))

pantheon_plot_b <- plot_belief_winloss_stack(
    pantheon_stats,
    title = "Pantheon Pick Frequency And Performance",
    caption = CAPTION,
    theme_fn = theme_report_dark,
    text_color = IPSUM_VP_DARK_FG, bar_outline = IPSUM_VP_DARK_BG
) + caption_theme("b")
save_plot_dark(pantheon_plot_b, "06b_pantheon_freq_perf",
               width = 13, height = max(6, 0.48 * nrow(pantheon_stats) + 3))

# --- Turn-picked ridgeline variants --------------------------------------
ridge_height <- max(6, 0.55 * nrow(pantheon_stats) + 3)

pantheon_ridge_a <- plot_belief_turn_ridge(
    pantheon_picks, pantheon_stats,
    title = "Pantheon - Turn Picked Distribution",
    caption = CAPTION,
    theme_fn = theme_report, bg = IPSUM_VP_BG,
    viridis_opt = "viridis", vline_color = "white"
) + caption_theme("a")
save_plot(pantheon_ridge_a, "06a_pantheon_turn_ridgeline",
          width = 13, height = ridge_height)

pantheon_ridge_b <- plot_belief_turn_ridge(
    pantheon_picks, pantheon_stats,
    title = "Pantheon - Turn Picked Distribution",
    caption = CAPTION,
    theme_fn = theme_report_dark, bg = IPSUM_VP_DARK_BG,
    viridis_opt = "inferno", begin = 0.05, end = 0.95,
    vline_color = IPSUM_VP_DARK_BG
) + caption_theme("b")
save_plot_dark(pantheon_ridge_b, "06b_pantheon_turn_ridgeline",
               width = 13, height = ridge_height)
