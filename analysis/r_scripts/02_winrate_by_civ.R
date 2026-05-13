# 02: Win rate per civilization, stacked by victory type.
# Produces:
#   02a_winrate_by_civ_stacked_bars.png  light theme + vtc_lut_a
#   02b_winrate_by_civ_stacked_bars.png  dark theme  + vtc_lut_b
source("r_scripts/common.R")

vtype_cols <- c(
    "culture_victories",
    "science_victories",
    "domination_victories",
    "diplomatic_victories",
    "time_victories"
)

winrate_long <- power_ranking_df %>%
    mutate(across(all_of(vtype_cols),
                  ~ suppressWarnings(as.numeric(as.character(.))) %>% replace_na(0))) %>%
    mutate(
        winrate     = as.numeric(winrate),
        count_games = as.numeric(count_games),
        total_wins  = rowSums(across(all_of(vtype_cols)))
    ) %>%
    pivot_longer(cols = all_of(vtype_cols),
                 names_to = "vtype_raw", values_to = "wins") %>%
    mutate(
        victory_type = factor(
            recode(vtype_raw,
                   culture_victories    = "Cultural",
                   science_victories    = "Science",
                   domination_victories = "Domination",
                   diplomatic_victories = "Diplomatic",
                   time_victories       = "Time"),
            levels = VICTORY_LEVELS),
        share_winrate = ifelse(count_games > 0, wins / count_games, 0)
    )

# Drop victory types that never occur in the dataset so they don't appear
# in the legend.  Also drop rows whose victory_type couldn't be resolved
# (NA): otherwise scale_fill_manual would emit an "NA" swatch.
winrate_long <- winrate_long %>% filter(!is.na(victory_type))

present_vtypes <- winrate_long %>%
    group_by(victory_type) %>%
    summarise(total = sum(wins), .groups = "drop") %>%
    filter(total > 0) %>%
    pull(victory_type) %>%
    as.character()
winrate_long <- winrate_long %>%
    mutate(victory_type = factor(as.character(victory_type),
                                 levels = intersect(VICTORY_LEVELS, present_vtypes)))

civ_order <- winrate_long %>%
    group_by(civ) %>%
    summarise(total_winrate = sum(share_winrate), .groups = "drop") %>%
    arrange(desc(total_winrate)) %>%
    pull(civ)

winrate_long <- winrate_long %>%
    mutate(civ = factor(civ, levels = civ_order))

totals_df <- winrate_long %>%
    group_by(civ) %>%
    summarise(total_winrate = sum(share_winrate),
              total_wins    = sum(wins),
              .groups = "drop")

caption_text <- default_caption()

build_winrate <- function(lut, bg, theme_fn, text_color, ref_text_color,
                          caption_color, with_caption = TRUE) {
    p <- ggplot(winrate_long,
           aes(x = civ, y = share_winrate, fill = victory_type)) +
        geom_col(width = 0.78, color = bg, linewidth = 0.25) +
        geom_hline(yintercept = 0.125, linetype = "dashed",
                   color = text_color, linewidth = 0.6) +
        annotate("text", x = Inf, y = 0.125,
                 label = "average win rate (12.5%)",
                 hjust = 1.05, vjust = -0.5,
                 size = 3.4, color = ref_text_color, fontface = "italic") +
        geom_text(data = totals_df,
                  aes(x = civ, y = total_winrate,
                      label = percent(total_winrate, accuracy = 1)),
                  inherit.aes = FALSE,
                  vjust = -0.4, size = 3, color = text_color) +
        scale_fill_manual(values = lut, name = "Victory type",
                          drop = FALSE, na.translate = FALSE) +
        scale_y_continuous(labels = percent_format(accuracy = 1),
                           expand = expansion(mult = c(0, 0.10))) +
        labs(title = "Win Rate By Civilization",
             caption = if (with_caption) caption_text else NULL,
             x = "Civilization", y = "Winrate") +
        theme_fn(base_size = 12) +
        theme(
            axis.text.x        = element_text(angle = 45, hjust = 1, vjust = 1, size = 9),
            panel.grid.major.x = element_blank(),
            plot.caption       = element_text(color = caption_color, size = 11,
                                              hjust = 1, face = "italic")
        )
    p
}

save_plot(
    build_winrate(vtc_lut_a, IPSUM_VP_BG, theme_report,
                  text_color = "grey25", ref_text_color = "grey20",
                  caption_color = "grey25"),
    "02a_winrate_by_civ_stacked_bars", width = 14, height = 7)

save_plot_dark(
    build_winrate(vtc_lut_b, IPSUM_VP_DARK_BG, theme_report_dark,
                  text_color = IPSUM_VP_DARK_FG, ref_text_color = "grey75",
                  caption_color = "grey60"),
    "02b_winrate_by_civ_stacked_bars", width = 14, height = 7)

# Caption-less twin used by the victory-overview composite (script 20).
save_plot_dark(
    build_winrate(vtc_lut_b, IPSUM_VP_DARK_BG, theme_report_dark,
                  text_color = IPSUM_VP_DARK_FG, ref_text_color = "grey75",
                  caption_color = "grey60",
                  with_caption = FALSE),
    "02b_winrate_by_civ_stacked_bars_nocap", width = 14, height = 7)
