# 10: Wonder completion turn distributions, ridgeline plot per era.
# - One facet per era, free x scale.
# - One density ridge per wonder; y = wonder, x = turn.
# - Fill is a gradient on `turn`, synced across all facets.
source("r_scripts/common.R")

wonders_df <- load_spark_csv("wonders")
wonders_df <- synth_clone_per_game(wonders_df, "wonders_df")

wonder_eras <- read_csv("../db_util/out/wonder_eras.csv", show_col_types = FALSE) %>%
    rename(wonder = Name, era = Era)

ERA_LEVELS <- c("Ancient", "Classical", "Medieval", "Renaissance",
                "Industrial", "Modern", "Postmodern", "Future")

wonder_turns_df <- wonders_df %>%
    inner_join(wonder_eras, by = "wonder") %>%
    filter(!is.na(turn), turn > 0) %>%
    mutate(era = factor(era, levels = ERA_LEVELS))

# Order wonders within each era by descending median turn so the
# earliest-built wonder sits at the top of each facet (matches reference).
wonder_turns_df <- wonder_turns_df %>%
    group_by(era) %>%
    mutate(wonder = fct_reorder(wonder, turn, .fun = median, .desc = TRUE)) %>%
    ungroup()

turn_range <- range(wonder_turns_df$turn, na.rm = TRUE)

build_wonder_ridge <- function(theme_fn, bg, viridis_opt = "viridis",
                               begin = 0, end = 1, strip_text_color = "black") {
    ggplot(wonder_turns_df,
           aes(x = turn, y = wonder, fill = after_stat(x))) +
        geom_density_ridges_gradient(scale = 2.0, rel_min_height = 0.01,
                                     color = bg, linewidth = 0.3) +
        scale_fill_viridis_c(option = viridis_opt, limits = turn_range,
                             begin = begin, end = end,
                             name = "Turn", guide = "none") +
        facet_wrap(~ era, scales = "free", ncol = 3) +
        labs(title = "Wonder Completion Turn Distributions",
             x = "turn", y = "wonder") +
        theme_fn(base_size = 12) +
        theme(panel.grid.major.y = element_blank(),
              strip.text = element_text(face = "bold", color = strip_text_color))
}

save_plot(build_wonder_ridge(theme_report, IPSUM_VP_BG, "viridis"),
          "10a_wonder_completion_ridgeline", width = 18, height = 14)
save_plot_dark(build_wonder_ridge(theme_report_dark, IPSUM_VP_DARK_BG,
                                  viridis_opt = "inferno",
                                  begin = 0.05, end = 0.95,
                                  strip_text_color = "white"),
               "10b_wonder_completion_ridgeline", width = 18, height = 14)
