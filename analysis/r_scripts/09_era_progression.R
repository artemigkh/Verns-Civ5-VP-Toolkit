# 09: Era progression time -- violin per era.
source("r_scripts/common.R")

era_transitions_df <- load_spark_csv("era_transitions") %>%
    mutate(era = as.integer(era))
era_transitions_df <- synth_clone_per_game(era_transitions_df, "era_transitions_df")

era_entry_df <- era_transitions_df %>%
    group_by(game_id, civ, era) %>%
    summarise(turn = min(turn), .groups = "drop") %>%
    filter(era >= 2, era <= 9) %>%
    mutate(era_name = factor(era_lut[as.character(era)],
                             levels = unname(era_lut)[2:9]))

era_summary <- era_entry_df %>%
    group_by(era_name) %>%
    summarise(median_turn = median(turn),
              n           = dplyr::n(),
              .groups     = "drop")

n_civ_games <- era_entry_df %>% distinct(game_id, civ) %>% nrow()
era_summary <- era_summary %>% mutate(reach_pct = n / n_civ_games)

build_era_violin <- function(theme_fn, bg, box_color, outlier_fill) {
    # Limit outliers to top 8 per group
    outlier_limit_df <- era_entry_df %>%
        group_by(era_name) %>%
        mutate(
            q1 = quantile(turn, 0.25),
            q3 = quantile(turn, 0.75),
            iqr = q3 - q1,
            lower = q1 - 1.5 * iqr,
            upper = q3 + 1.5 * iqr,
            is_outlier = turn < lower | turn > upper,
            rank_outlier = rank(abs(turn - median(turn)), ties.method = "first")
        ) %>%
        ungroup() %>%
        mutate(show_outlier = is_outlier & rank_outlier <= 8)
    
    ggplot(era_entry_df,
           aes(x = era_name, y = turn, fill = era_name)) +
        geom_violin(trim = TRUE, scale = "width", alpha = 0.85,
                    color = bg, linewidth = 0.45) +
        geom_boxplot(width = 0.18, alpha = 0.55, color = box_color,
                     linewidth = 0.4, outlier.shape = NA,
                     show.legend = FALSE) +
        geom_point(data = filter(outlier_limit_df, show_outlier),
                   aes(x = era_name, y = turn),
                   shape = 21, fill = outlier_fill, color = box_color,
                   size = 1.4, alpha = 0.7, show.legend = FALSE) +
        scale_fill_viridis_d(option = "mako", direction = -1, end = 0.92,
                             guide = "none") +
        scale_y_continuous(labels = comma,
                           expand = expansion(mult = c(0.02, 0.10))) +
        labs(title = "Distribution of turns that civs first entered an era",
             x = NULL, y = "Turn") +
        theme_fn(base_size = 13) +
        theme(panel.grid.major.x = element_blank())
}

save_plot(build_era_violin(theme_report, IPSUM_VP_BG,
                           box_color = "grey15", outlier_fill = "grey20"),
          "09a_era_progression_time_violin", width = 13, height = 7)
save_plot_dark(build_era_violin(theme_report_dark, IPSUM_VP_DARK_BG,
                                box_color = "grey85", outlier_fill = "grey75"),
               "09b_era_progression_time_violin", width = 13, height = 7)
