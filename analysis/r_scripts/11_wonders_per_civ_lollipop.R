# 11: Average wonders constructed per game by civilization (lollipop).
# - x: mean wonders per game (total wonders / games played by civ)
# - y: civilization, ordered by mean (descending so the top civ is at top)
# - Point fill from civ_colors.csv, outline from civ_bg_colors.csv.
source("r_scripts/common.R")

wonders_df <- load_spark_csv("wonders")
wonders_df <- synth_clone_per_game(wonders_df, "wonders_df")

# Restrict to wonders listed in wonder_eras.csv (filters out non-wonder
# entries like Palace, projects, etc.).
wonder_name_filter <- read_csv("../db_util/out/wonder_eras.csv", show_col_types = FALSE)$Name
wonders_df <- wonders_df %>% filter(wonder %in% wonder_name_filter)

# Load civ palettes (RGB 0-255) and convert to hex.
rgb_to_hex <- function(r, g, b) {
    rgb(pmin(pmax(r, 0), 255) / 255,
        pmin(pmax(g, 0), 255) / 255,
        pmin(pmax(b, 0), 255) / 255)
}

civ_fill_src <- read_csv("../db_util/out/civ_bg_colors.csv", show_col_types = FALSE) %>%
    mutate(hex = rgb_to_hex(red, green, blue))
civ_fill_lut <- setNames(civ_fill_src$hex, civ_fill_src$civ)

civ_outline_src <- read_csv("../db_util/out/civ_colors.csv", show_col_types = FALSE) %>%
    mutate(hex = rgb_to_hex(red, green, blue))
civ_outline_lut <- setNames(civ_outline_src$hex, civ_outline_src$civ)

# Wonders built per civ across all games.
wonders_per_civ <- wonders_df %>%
    group_by(civ) %>%
    summarise(total_wonders = n(), .groups = "drop")

# Games each civ participated in (count distinct games from wonders_df).
# Note: power_ranking_df only contains partial data (~3 games per civ max),
# so we count actual game participation directly from the wonders data.
games_per_civ <- wonders_df %>%
    group_by(civ) %>%
    summarise(count_games = n_distinct(game_id), .groups = "drop")

avg_wonders_df <- wonders_per_civ %>%
    inner_join(games_per_civ, by = "civ") %>%
    mutate(avg_wonders = total_wonders / count_games) %>%
    arrange(avg_wonders) %>%
    mutate(civ = factor(civ, levels = civ))

# Fall back to grey for any civ missing from the palette CSVs.
fill_vals    <- ifelse(is.na(civ_fill_lut[as.character(avg_wonders_df$civ)]),
                       "#cccccc",
                       civ_fill_lut[as.character(avg_wonders_df$civ)])
outline_vals <- ifelse(is.na(civ_outline_lut[as.character(avg_wonders_df$civ)]),
                       "#333333",
                       civ_outline_lut[as.character(avg_wonders_df$civ)])
names(fill_vals)    <- as.character(avg_wonders_df$civ)
names(outline_vals) <- as.character(avg_wonders_df$civ)

build_lollipop <- function(theme_fn, segment_color, label_color) {
    ggplot(avg_wonders_df,
           aes(x = avg_wonders, y = civ,
               fill = civ, color = civ)) +
        geom_segment(aes(x = 0, xend = avg_wonders,
                         y = civ, yend = civ),
                     color = segment_color, linewidth = 0.6) +
        geom_point(shape = 21, size = 5, stroke = 1.1) +
        geom_text(aes(label = sprintf("%.1f", avg_wonders)),
                  hjust = -0.35, nudge_x = 0.3, size = 4.8,
                  color = label_color, show.legend = FALSE) +
        scale_fill_manual(values = fill_vals, guide = "none") +
        scale_color_manual(values = outline_vals, guide = "none") +
        scale_x_continuous(expand = expansion(mult = c(0, 0.10))) +
        labs(title = "Avg Wonders Constructed Per Game by Civ",
             x = "Mean wonders per game", y = "Civilization") +
        theme_fn(base_size = 12) +
        theme(panel.grid.major.y = element_blank())
}

save_plot(build_lollipop(theme_report, "grey55", "grey20"),
          "11a_wonders_per_civ_lollipop", width = 11, height = 12)
save_plot_dark(build_lollipop(theme_report_dark, "grey55", IPSUM_VP_DARK_FG),
               "11b_wonders_per_civ_lollipop", width = 11, height = 12)
