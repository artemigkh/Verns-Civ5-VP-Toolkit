# 07: Founder beliefs (and follower beliefs picked at found time)
#     frequency + win rate, side by side.
source("r_scripts/common.R")

rel <- load_religion_data()

beliefs_meta <- read_csv(file.path("..", "db_util", "out", "beliefs.csv"),
                         show_col_types = FALSE)

founder_belief_names <- beliefs_meta %>%
    filter(Founder == 1) %>% pull(ShortDescription)
follower_belief_names <- beliefs_meta %>%
    filter(Follower == 1) %>% pull(ShortDescription)

found_picks <- rel$choices %>% filter(type == "religion_founded")
found_time_stats <- belief_pick_stats(rel$choices, "religion_founded",
                                      rel$categories)

founder_stats <- found_time_stats %>%
    filter(belief %in% founder_belief_names)
follower_at_found_stats <- found_time_stats %>%
    filter(belief %in% follower_belief_names)

founder_picks <- found_picks %>% filter(belief %in% founder_belief_names)
follower_at_found_picks <- found_picks %>% filter(belief %in% follower_belief_names)

# --- Win/loss stacked bars (side by side) --------------------------------
build_winloss_pair <- function(theme_fn, text_color, bar_outline, variant) {
    left <- plot_belief_winloss_stack(
        founder_stats,
        title = "Founders - Pick Frequency and Performance",
        theme_fn = theme_fn,
        text_color = text_color, bar_outline = bar_outline
    )
    right <- plot_belief_winloss_stack(
        follower_at_found_stats,
        title = "Follower Beliefs at Found Time - Pick Frequency and Performance",
        theme_fn = theme_fn,
        text_color = text_color, bar_outline = bar_outline
    )
    (left + right) + patchwork::plot_layout(ncol = 2) +
        patchwork::plot_annotation(
            caption = default_caption(),
            theme = theme_fn(base_size = 13) + caption_theme(variant)
        )
}

panel_rows <- max(nrow(founder_stats), nrow(follower_at_found_stats))
plot_height <- max(6, 0.48 * panel_rows + 3)
plot_width  <- 26

save_plot(build_winloss_pair(theme_report, "grey25", "grey25", "a"),
          "07a_founder_beliefs_freq_perf",
          width = plot_width, height = plot_height)
save_plot_dark(build_winloss_pair(theme_report_dark,
                                  IPSUM_VP_DARK_FG, IPSUM_VP_DARK_BG, "b"),
               "07b_founder_beliefs_freq_perf",
               width = plot_width, height = plot_height)

# --- Turn-picked ridgeline pair ------------------------------------------
build_ridge_pair <- function(theme_fn, bg, viridis_opt,
                             begin = 0, end = 1, vline_color = "white",
                             variant = "a") {
    left <- plot_belief_turn_ridge(
        founder_picks, founder_stats,
        title = "Founders - Turn Picked Distribution",
        theme_fn = theme_fn, bg = bg,
        viridis_opt = viridis_opt, begin = begin, end = end,
        vline_color = vline_color
    )
    right <- plot_belief_turn_ridge(
        follower_at_found_picks, follower_at_found_stats,
        title = "Follower Beliefs at Found Time - Turn Picked Distribution",
        theme_fn = theme_fn, bg = bg,
        viridis_opt = viridis_opt, begin = begin, end = end,
        vline_color = vline_color
    )
    (left + right) + patchwork::plot_layout(ncol = 2) +
        patchwork::plot_annotation(
            caption = default_caption(),
            theme = theme_fn(base_size = 13) + caption_theme(variant)
        )
}

ridge_height <- max(6, 0.55 * panel_rows + 3)

save_plot(build_ridge_pair(theme_report, IPSUM_VP_BG, "viridis",
                           vline_color = "white", variant = "a"),
          "07a_founder_beliefs_turn_ridgeline",
          width = plot_width, height = ridge_height)
save_plot_dark(build_ridge_pair(theme_report_dark, IPSUM_VP_DARK_BG,
                                "inferno", begin = 0.05, end = 0.95,
                                vline_color = IPSUM_VP_DARK_BG, variant = "b"),
               "07b_founder_beliefs_turn_ridgeline",
               width = plot_width, height = ridge_height)
