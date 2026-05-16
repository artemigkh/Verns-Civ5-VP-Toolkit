# 14b_wonders_stacked_bar.R
# Stacked bar chart: total wonders built per civ, segmented by era.
# Y-axis: average wonders per game (normalised by civ game count).
# Civs ordered descending by total avg wonders (top at top -> horizontal bars).
# Era segments use a progressive viridis palette; no civ colors used.
source("r_scripts/common.R")

# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------
wonders_df <- load_spark_csv("wonders")
wonders_df <- synth_clone_per_game(wonders_df, "wonders_df")

# Wonder -> era lookup
wonder_era_df <- read_csv("wonder_eras.csv", show_col_types = FALSE) %>%
    rename(wonder = Name, era = Era)

ERA_ORDER <- c("Ancient", "Classical", "Medieval", "Renaissance",
               "Industrial", "Modern", "Atomic", "Information")

# Filter to real wonders only, join era
wonders_df <- wonders_df %>%
    filter(wonder %in% wonder_era_df$wonder) %>%
    left_join(wonder_era_df, by = "wonder") %>%
    mutate(era = factor(era, levels = ERA_ORDER))

# Games per civ for normalisation
games_per_civ <- wonders_df %>%
    group_by(civ) %>%
    summarise(count_games = n_distinct(game_id), .groups = "drop")

# Avg wonders per game per civ per era
stacked_df <- wonders_df %>%
    group_by(civ, era) %>%
    summarise(total = n(), .groups = "drop") %>%
    left_join(games_per_civ, by = "civ") %>%
    mutate(avg = total / count_games)

# Civ order: descending total avg wonders (top civ at top of horizontal bars)
civ_order <- stacked_df %>%
    group_by(civ) %>%
    summarise(total_avg = sum(avg), .groups = "drop") %>%
    arrange(total_avg) %>%
    pull(civ)

stacked_df <- stacked_df %>%
    mutate(civ = factor(civ, levels = civ_order))

# Totals per civ for end-of-bar label
totals_df <- stacked_df %>%
    group_by(civ) %>%
    summarise(total_avg = sum(avg), .groups = "drop") %>%
    mutate(civ = factor(civ, levels = civ_order))

n_eras <- length(ERA_ORDER)

# Palette variants: named list of (option, begin, end)
palette_variants <- list(
    b = list(option = "inferno",  begin = 0.05, end = 0.95),  # 13b match
    c = list(option = "plasma",   begin = 0.05, end = 0.95),
    d = list(option = "viridis",  begin = 0.10, end = 0.95),
    e = list(option = "turbo",    begin = 0.05, end = 0.95),
    f = list(option = "rocket",   begin = 0.05, end = 0.95)
)

# ---------------------------------------------------------------------------
# Plot builder
# ---------------------------------------------------------------------------
build_stacked <- function(era_colors, theme_fn, bg, label_color) {
    ggplot(stacked_df, aes(y = civ, x = avg, fill = era)) +
        geom_col(width = 0.72, color = "grey25", linewidth = 0.25,
                 position = position_stack(reverse = TRUE)) +
        geom_text(data = totals_df,
                  aes(y = civ, x = total_avg,
                      label = sprintf("%.1f", total_avg)),
                  inherit.aes = FALSE,
                  hjust = -0.2, size = 3.2, color = label_color) +
        scale_fill_manual(values = era_colors,
                          breaks = ERA_ORDER,
                          name   = "Wonder Era",
                          drop   = FALSE) +
        scale_x_continuous(expand = expansion(mult = c(0, 0.11)),
                           labels = function(x) sprintf("%.1f", x)) +
        labs(title   = "Avg Wonders Built per Game by Civ & Era",
             caption = default_caption(),
             x = "Mean wonders per game", y = NULL) +
        guides(fill = guide_legend(nrow = 1, reverse = FALSE,
                                   override.aes = list(linewidth = 0))) +
        theme_fn(base_size = 12) +
        theme(panel.grid.major.y = element_blank(),
              legend.position    = "top",
              legend.title       = element_text(face = "bold",
                                                color = label_color),
              legend.text        = element_text(color = label_color))
}

for (variant_id in names(palette_variants)) {
    v <- palette_variants[[variant_id]]
    era_colors <- setNames(
        viridisLite::viridis(n_eras, option = v$option,
                             begin = v$begin, end = v$end),
        ERA_ORDER
    )
    save_plot_dark(
        build_stacked(era_colors, theme_report_dark,
                      IPSUM_VP_DARK_BG, IPSUM_VP_DARK_FG) +
            caption_theme("b"),
        paste0("14", variant_id, "_wonders_stacked_bar"),
        width = 13, height = 13
    )
}
