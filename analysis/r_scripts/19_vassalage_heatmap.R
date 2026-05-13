# 19: Vassalage frequency heatmap with marginal totals.
# Each cell is the total count of times `master` (y-axis) acquired `vassal`
# (x-axis) across all autoplay games. Civs on both axes are the canonical
# 43 from power_ranking_df, so the grid is square even when some pairings
# never occur.
#
# Top marginal:   "Avg Times Vassalized / Game" -- distinct games the civ
#                 was a vassal in, divided by total games the civ played.
# Right marginal: "Avg Vassals / Game" -- total vassalage deals where the
#                 civ was master, divided by total games the civ played
#                 (same denominator as the top marginal).
#
# Produces:
#   19a_vassalage_heatmap.png  light theme
#   19b_vassalage_heatmap.png  dark theme
source("r_scripts/common.R")

vassalage_df <- load_spark_csv("vassalage")

civ_levels <- sort(unique(power_ranking_df$civ))

# Per-civ game counts -- denominator for the marginal averages.
civ_games <- power_ranking_df %>%
    transmute(civ, games = as.numeric(count_games))

pair_counts <- vassalage_df %>%
    filter(master %in% civ_levels, vassal %in% civ_levels) %>%
    count(master, vassal, name = "n")

# Full 43x43 grid so empty cells render explicitly.
grid_df <- expand_grid(
    master = factor(civ_levels, levels = rev(civ_levels)),
    vassal = factor(civ_levels, levels = civ_levels)
) %>%
    left_join(
        pair_counts %>%
            mutate(master = factor(master, levels = rev(civ_levels)),
                   vassal = factor(vassal, levels = civ_levels)),
        by = c("master", "vassal")
    ) %>%
    mutate(n = replace_na(n, 0L))

master_totals <- grid_df %>%
    group_by(master) %>%
    summarise(total = sum(n), .groups = "drop") %>%
    left_join(
        civ_games %>%
            mutate(master = factor(civ, levels = rev(civ_levels))) %>%
            select(master, games),
        by = "master"
    ) %>%
    mutate(games = replace_na(games, 0),
           avg = ifelse(games > 0, total / games, 0),
           # Re-cast: the join coerces `master` to character, which would
           # otherwise be plotted alphabetically ascending (i.e. flipped
           # vs. the heatmap rows).
           master = factor(master, levels = rev(civ_levels)))

# For "avg times vassalized per game" we dedupe at the (game_id, vassal)
# level: a civ that gets vassalized by two different masters in the same
# game still only counts once toward this per-game average.
vassal_per_game <- vassalage_df %>%
    filter(master %in% civ_levels, vassal %in% civ_levels) %>%
    distinct(game_id, vassal) %>%
    count(vassal, name = "games_vassalized")

vassal_totals <- tibble(vassal = civ_levels) %>%
    left_join(vassal_per_game, by = "vassal") %>%
    left_join(civ_games, by = c("vassal" = "civ")) %>%
    mutate(games_vassalized = replace_na(games_vassalized, 0L),
           avg = ifelse(games > 0, games_vassalized / games, 0),
           vassal = factor(vassal, levels = civ_levels))

max_n <- max(grid_df$n)
caption_text <- default_caption()

build_main <- function(theme_fn, bg, fg, low_fill, high_fill, tile_border) {
    # Separator lines every 4 civs (placed between cells, at x = 4.5, 8.5, …).
    n_civs   <- length(civ_levels)
    sep_pos  <- seq(4, n_civs - 1, by = 4) + 0.5

    ggplot(grid_df, aes(x = vassal, y = master, fill = n)) +
        geom_tile(color = tile_border, linewidth = 0.25) +
        geom_text(data = grid_df %>% filter(n > 0),
                  aes(label = n),
                  color = fg,
                  size = 2.6, fontface = "bold",
                  show.legend = FALSE) +
        geom_vline(xintercept = sep_pos, color = fg, linewidth = 0.35, alpha = 0.5) +
        geom_hline(yintercept = sep_pos, color = fg, linewidth = 0.35, alpha = 0.5) +
        scale_fill_gradient(
            low = low_fill, high = high_fill,
            limits = c(0, max(1L, max_n)),
            guide = "none"
        ) +
        scale_x_discrete(position = "bottom", expand = c(0, 0)) +
        scale_y_discrete(expand = c(0, 0)) +
        labs(x = "Vassal", y = "Master") +
        theme_fn(base_size = 12) +
        theme(
            axis.text.x        = element_text(angle = 45, hjust = 1, vjust = 1, size = 9),
            axis.text.y        = element_text(size = 9),
            panel.grid.major   = element_blank(),
            panel.grid.minor   = element_blank(),
            legend.position    = "none",
            plot.margin        = margin(0, 0, 2, 2)
        )
}

fmt_avg <- function(x) sprintf("%.2f", x)

build_top_marginal <- function(theme_fn, fg, bar_fill) {
    ggplot(vassal_totals, aes(x = vassal, y = avg)) +
        geom_col(fill = bar_fill, width = 0.8) +
        geom_text(aes(label = fmt_avg(avg)),
                  vjust = -0.3, size = 2.4, color = fg) +
        # Civ name as annotation above the number, rotated.
        geom_text(aes(label = vassal, y = avg),
                  angle = 90, hjust = 0, vjust = 0.5,
                  nudge_y = max(vassal_totals$avg) * 0.35,
                  color = fg, size = 2.5, fontface = "bold") +
        scale_x_discrete(expand = c(0, 0)) +
        scale_y_continuous(expand = expansion(mult = c(0, 0.55))) +
        labs(title = "Avg Times Vassalized / Game", x = NULL, y = NULL) +
        theme_fn(base_size = 12) +
        theme(
            axis.text.x        = element_blank(),
            axis.ticks.x       = element_blank(),
            axis.text.y        = element_blank(),
            axis.ticks.y       = element_blank(),
            panel.grid.major   = element_blank(),
            panel.grid.minor   = element_blank(),
            plot.title         = element_text(face = "bold", size = 12,
                                              hjust = 0.5, color = fg),
            plot.margin        = margin(2, 0, 4, 2)
        )
}

build_right_marginal <- function(theme_fn, fg, bar_fill) {
    df <- master_totals %>% mutate(strip = "Avg Vassals / Game")
    ggplot(df, aes(y = master, x = avg)) +
        geom_col(fill = bar_fill, width = 0.8) +
        geom_text(aes(label = fmt_avg(avg)),
                  hjust = -0.15, size = 2.4, color = fg) +
        # Civ name as annotation to the right of the number.
        geom_text(aes(label = master, x = avg),
                  hjust = 0, vjust = 0.5,
                  nudge_x = max(master_totals$avg) * 0.35,
                  color = fg, size = 2.5, fontface = "bold") +
        facet_wrap(~ strip, strip.position = "right") +
        scale_y_discrete(expand = c(0, 0)) +
        scale_x_continuous(expand = expansion(mult = c(0, 0.65))) +
        labs(x = NULL, y = NULL) +
        theme_fn(base_size = 12) +
        theme(
            axis.text.x        = element_blank(),
            axis.ticks.x       = element_blank(),
            axis.text.y        = element_blank(),
            axis.ticks.y       = element_blank(),
            panel.grid.major   = element_blank(),
            panel.grid.minor   = element_blank(),
            strip.placement    = "outside",
            strip.text.y.right = element_text(face = "bold", size = 12,
                                              color = fg, angle = -90),
            plot.margin        = margin(0, 2, 2, 4)
        )
}

compose <- function(theme_fn, bg, fg, low_fill, high_fill, tile_border,
                    bar_fill, caption_color) {
    main  <- build_main(theme_fn, bg, fg, low_fill, high_fill, tile_border)
    top   <- build_top_marginal(theme_fn, fg, bar_fill)
    right <- build_right_marginal(theme_fn, fg, bar_fill)

    annotation_theme <- theme_fn(base_size = 13) +
        theme(
            plot.title   = element_text(face = "bold", size = 18, color = fg),
            plot.caption = element_text(color = caption_color, size = 11,
                                        hjust = 1, face = "italic")
        )

    # `design` puts the top marginal above the heatmap and the right
    # marginal beside the heatmap; the top-right cell is left blank
    # (`#`) so no white square is rendered there.
    design <- "
AA#
BBC
"
    (top + main + right) +
        plot_layout(
            design  = design,
            widths  = c(5, 0, 1),
            heights = c(1, 5)
        ) +
        plot_annotation(
            title   = "Vassalage Frequencies",
            caption = caption_text,
            theme   = annotation_theme
        )
}

save_plot(
    compose(theme_report, IPSUM_VP_BG, "grey25",
            low_fill = "#f7f4ef", high_fill = "#3b0d68",
            tile_border = IPSUM_VP_BG,
            bar_fill = "#3b0d68", caption_color = "grey25"),
    "19a_vassalage_heatmap", width = 15, height = 14)

save_plot_dark(
    compose(theme_report_dark, IPSUM_VP_DARK_BG, IPSUM_VP_DARK_FG,
            low_fill = "#1f1b18", high_fill = "#ff9900",
            tile_border = IPSUM_VP_DARK_BG,
            bar_fill = "#ff9900", caption_color = IPSUM_VP_DARK_FG),
    "19b_vassalage_heatmap", width = 15, height = 14)
