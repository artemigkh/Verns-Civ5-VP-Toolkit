# 16b: Policy-branch WIN RATE (normalized) -- vertical stacked bars, one bar
#      per branch, height = wins per branch / times branch was opened, stacked
#      by victory type (each segment = victory_type wins / branch opens).
# Variant of 16_policy_branch_wins_bars.R.
# Produces:
#   16c_policy_branch_winrate_bars.png   light theme + vtc_lut_a
#   16d_policy_branch_winrate_bars.png   dark theme  + vtc_lut_b
source("r_scripts/common.R")

branch_stats_df <- load_spark_csv("branch_stats")
branch_stats_df <- synth_clone_per_game(branch_stats_df, "branch_stats_df")

BRANCH_NAMES <- c(
    "Tradition", "Progress", "Authority",
    "Fealty",    "Statecraft", "Artistry",
    "Industry",  "Imperialism", "Rationalism",
    "Freedom",   "Order",       "Autocracy"
)

branch_filtered <- branch_stats_df %>%
    mutate(branch = as.integer(branch)) %>%
    filter(!is.na(branch), branch >= 0, branch <= 11) %>%
    mutate(branch_name = factor(BRANCH_NAMES[branch + 1], levels = BRANCH_NAMES))

# Denominator: total times each branch was opened (one row per (game, civ, branch)).
opens_per_branch <- branch_filtered %>%
    count(branch_name, .drop = FALSE, name = "opens")

# Numerator: wins per (branch, victory_type).
wins_per_branch <- branch_filtered %>%
    filter(!is.na(victory_type), nzchar(as.character(victory_type))) %>%
    mutate(victory_type = factor(as.character(victory_type),
                                 levels = VICTORY_LEVELS)) %>%
    count(branch_name, victory_type, name = "wins")

# Drop victory types absent from the data so the legend stays clean.
present_vtypes <- wins_per_branch %>%
    group_by(victory_type) %>%
    summarise(total = sum(wins), .groups = "drop") %>%
    filter(total > 0) %>%
    pull(victory_type) %>%
    as.character()
wins_per_branch <- wins_per_branch %>%
    mutate(victory_type = factor(as.character(victory_type),
                                 levels = intersect(VICTORY_LEVELS, present_vtypes)))

winrate_long <- wins_per_branch %>%
    left_join(opens_per_branch, by = "branch_name") %>%
    mutate(winrate = ifelse(opens > 0, wins / opens, 0))

totals_df <- winrate_long %>%
    group_by(branch_name) %>%
    summarise(total_winrate = sum(winrate),
              opens         = first(opens),
              .groups = "drop")

n_games_eff <- length(unique(branch_stats_df$game_id))
caption_text <- default_caption(n_games_eff)

build_bars <- function(lut, bg, theme_fn, text_color, caption_color) {
    ggplot(winrate_long,
           aes(x = branch_name, y = winrate, fill = victory_type)) +
        geom_col(width = 0.78, color = bg, linewidth = 0.25) +
        geom_text(data = totals_df,
                  aes(x = branch_name, y = total_winrate,
                      label = percent(total_winrate, accuracy = 1)),
                  inherit.aes = FALSE,
                  vjust = -0.2, size = 3.2,
                  color = text_color) +
        scale_fill_manual(values = lut, name = "Victory type", drop = FALSE) +
        scale_y_continuous(labels = percent_format(accuracy = 1),
                           expand = expansion(mult = c(0, 0.18))) +
        labs(title = "Win Rate by Policy Branch",
             x = "Policy branch", y = "Win rate") +
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
    "16c_policy_branch_winrate_bars", width = 12, height = 7)

save_plot_dark(
    build_bars(vtc_lut_b, IPSUM_VP_DARK_BG, theme_report_dark,
               text_color = IPSUM_VP_DARK_FG, caption_color = "grey60"),
    "16d_policy_branch_winrate_bars", width = 12, height = 7)
save_plot_dark_nocap(
    build_bars(vtc_lut_b, IPSUM_VP_DARK_BG, theme_report_dark,
               text_color = IPSUM_VP_DARK_FG, caption_color = "grey60"),
    "16d_policy_branch_winrate_bars_nocap", width = 12, height = 7)
