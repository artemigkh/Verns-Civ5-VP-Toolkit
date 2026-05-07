# 08: Technology research-time per era, ridgeline plot.
# Produces:
#   08a_tech_research_time_by_era_ridgeline.png  light viridis on warm-gray bg
#   08b_tech_research_time_by_era_ridgeline.png  inferno on dark bg
source("r_scripts/common.R")

tech_completion_df <- load_spark_csv("technology_completion_records") %>%
    mutate(gridx = as.integer(gridx_at_start),
           era_n = ((gridx - 1) %/% 2) + 1,
           tier  = ((gridx - 1) %%  2) + 1)
tech_completion_df <- synth_clone_per_game(tech_completion_df, "tech_completion_df")

tech_era_df <- tech_completion_df %>%
    filter(!is.na(era_n), era_n >= 1, era_n <= 9, duration > 0) %>%
    mutate(era_name = era_lut[as.character(era_n)],
           era_tier = case_when(
               era_n == 8 & tier == 1 ~ "Information T1",
               era_n == 8 & tier == 2 ~ "Information T2",
               era_n == 9 & tier == 1 ~ "Information T3",
               era_n == 9 & tier == 2 ~ "Future",
               TRUE ~ paste0(era_name, " T", tier)
           ))

# Order: Ancient T1 (top), Ancient T2, Classical T1, ... Future (bottom)
# For eras 1-7 (Ancient through Atomic), use standard T1/T2 labels
standard_eras <- as.vector(t(outer(unname(era_lut)[1:7], c("T1", "T2"), paste)))
# For Information and Future, use custom labels
special_eras <- c("Information T1", "Information T2", "Information T3", "Future")
era_tier_levels <- c(standard_eras, special_eras)

tech_era_df <- tech_era_df %>%
    mutate(era_tier = factor(era_tier, levels = rev(era_tier_levels))) %>%
    select(-era_name)

x_upper    <- as.numeric(quantile(tech_era_df$duration, 0.99))
turn_range <- c(0, x_upper)

build_ridge <- function(theme_fn, bg, viridis_opt = "viridis",
                        begin = 0, end = 1, vline_color = "white") {
    ggplot(tech_era_df,
           aes(x = duration, y = era_tier, fill = after_stat(x))) +
        geom_density_ridges_gradient(scale = 2.0, rel_min_height = 0.01,
                                     color = bg, linewidth = 0.4,
                                     bandwidth = 0.6,
                                     quantile_lines = TRUE,
                                     quantile_fun = function(x, ...) mean(x),
                                     vline_color = vline_color,
                                     vline_linetype = "dashed",
                                     vline_size = 0.6) +
        scale_fill_viridis_c(option = viridis_opt, limits = turn_range,
                             oob = scales::squish,
                             begin = begin, end = end, guide = "none") +
        scale_x_continuous(limits = turn_range,
                           expand = expansion(mult = c(0.01, 0.05))) +
        labs(title = "Technology Research Time by Era",
             x = "Turns to research", y = NULL) +
        theme_fn(base_size = 13) +
        theme(panel.grid.major.y = element_blank())
}

save_plot(build_ridge(theme_report, IPSUM_VP_BG, "viridis",
                      vline_color = "white"),
          "08a_tech_research_time_by_era_ridgeline",
          width = 12, height = 11)

save_plot_dark(
    build_ridge(theme_report_dark, IPSUM_VP_DARK_BG,
                viridis_opt = "inferno", begin = 0.05, end = 0.95,
                vline_color = "black"),
    "08b_tech_research_time_by_era_ridgeline",
    width = 12, height = 11)
