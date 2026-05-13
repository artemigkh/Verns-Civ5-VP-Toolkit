# 16: Policy-branch wins -- vertical stacked bars, one bar per branch,
#     stacked by victory type. Mirrors the `branch_count_df` SQL aggregation
#     in Report.ipynb (cell 35).
# Produces:
#   16a_policy_branch_wins_bars.png   light theme + vtc_lut_a
#   16b_policy_branch_wins_bars.png   dark theme  + vtc_lut_b
source("r_scripts/common.R")

branch_stats_df <- load_spark_csv("branch_stats")
branch_stats_df <- synth_clone_per_game(branch_stats_df, "branch_stats_df")

BRANCH_NAMES <- c(
    "Tradition", "Progress", "Authority",
    "Fealty",    "Statecraft", "Artistry",
    "Industry",  "Imperialism", "Rationalism",
    "Freedom",   "Order",       "Autocracy"
)

# branch_stats: one row per (game_id, civ) per branch opened. victory_type
# is non-null only on rows belonging to that game's winning civ.
wins_per_branch <- branch_stats_df %>%
    mutate(branch = as.integer(branch)) %>%
    filter(!is.na(branch), branch >= 0, branch <= 11,
           !is.na(victory_type), nzchar(as.character(victory_type))) %>%
    mutate(branch_name  = factor(BRANCH_NAMES[branch + 1], levels = BRANCH_NAMES),
           victory_type = factor(as.character(victory_type),
                                 levels = VICTORY_LEVELS)) %>%
    count(branch_name, victory_type, name = "wins")

# Drop victory types that never occur, so the legend only shows the ones
# present in the dataset.
present_vtypes <- wins_per_branch %>%
    group_by(victory_type) %>%
    summarise(total = sum(wins), .groups = "drop") %>%
    filter(total > 0) %>%
    pull(victory_type) %>%
    as.character()
wins_per_branch <- wins_per_branch %>%
    mutate(victory_type = factor(as.character(victory_type),
                                 levels = intersect(VICTORY_LEVELS, present_vtypes)))

totals_df <- wins_per_branch %>%
    group_by(branch_name) %>%
    summarise(total_wins = sum(wins), .groups = "drop")

n_games_eff <- length(unique(branch_stats_df$game_id))
caption_text <- default_caption(n_games_eff)

build_bars <- function(lut, bg, theme_fn, text_color, caption_color) {
    ggplot(wins_per_branch,
           aes(x = branch_name, y = wins, fill = victory_type)) +
        geom_col(width = 0.78, color = bg, linewidth = 0.25) +
        geom_text(data = totals_df,
                  aes(x = branch_name, y = total_wins,
                      label = total_wins),
                  inherit.aes = FALSE,
                  vjust = -0.4, size = 3.4, color = text_color) +
        scale_fill_manual(values = lut, name = "Victory type") +
        scale_y_continuous(expand = expansion(mult = c(0, 0.10))) +
        labs(title = "Wins by Policy Branch",
             caption = caption_text,
             x = "Policy branch", y = "Wins") +
        theme_fn(base_size = 12) +
        theme(
            axis.text.x        = element_text(angle = 45, hjust = 1, vjust = 1, size = 10),
            panel.grid.major.x = element_blank(),
            plot.caption       = element_text(color = caption_color, size = 11,
                                              hjust = 1, face = "italic")
        )
}

save_plot(
    build_bars(vtc_lut_a, IPSUM_VP_BG, theme_report,
               text_color = "grey25", caption_color = "grey25"),
    "16a_policy_branch_wins_bars", width = 12, height = 7)

save_plot_dark(
    build_bars(vtc_lut_b, IPSUM_VP_DARK_BG, theme_report_dark,
               text_color = IPSUM_VP_DARK_FG, caption_color = "grey60"),
    "16b_policy_branch_wins_bars", width = 12, height = 7)
save_plot_dark_nocap(
    build_bars(vtc_lut_b, IPSUM_VP_DARK_BG, theme_report_dark,
               text_color = IPSUM_VP_DARK_FG, caption_color = "grey60"),
    "16b_policy_branch_wins_bars_nocap", width = 12, height = 7)
