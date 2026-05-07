# 03: Religion attainment-time KDEs (pantheon / founded / enhanced / reformed).
source("r_scripts/common.R")

rel <- load_religion_data()
religion_choices_df <- rel$choices

attainment_df <- religion_choices_df %>%
    distinct(game_id, civ, type, turn) %>%
    mutate(type = factor(type,
                         levels = c("pantheon", "religion_founded",
                                    "religion_enhanced", "religion_reformed"),
                         labels = religion_event_labels[c("pantheon",
                                                          "religion_founded",
                                                          "religion_enhanced",
                                                          "religion_reformed")]))

attainment_summary <- attainment_df %>%
    group_by(type) %>%
    summarise(mean_turn   = mean(turn),
              median_turn = median(turn),
              n           = dplyr::n(),
              .groups = "drop")

print(attainment_summary)

palette_named <- setNames(
    religion_event_lut[c("pantheon", "religion_founded",
                         "religion_enhanced", "religion_reformed")],
    religion_event_labels[c("pantheon", "religion_founded",
                            "religion_enhanced", "religion_reformed")]
)

x_panel <- 350

# Long-format summary so vline linetype maps cleanly to a "Mean / Median" legend.
vline_df <- bind_rows(
    attainment_summary %>%
        transmute(type, stat = "Mean",   x = mean_turn),
    attainment_summary %>%
        transmute(type, stat = "Median", x = median_turn)
) %>%
    mutate(stat = factor(stat, levels = c("Mean", "Median")))

build_attainment <- function(theme_fn, bg) {
    ggplot(attainment_df, aes(x = turn, color = type)) +
        geom_density(bw = 5, linewidth = 1.0, key_glyph = "path") +
        geom_vline(data = vline_df,
                   aes(xintercept = x, color = type, linetype = stat),
                   linewidth = 0.4, alpha = 0.8, key_glyph = "path") +
        scale_color_manual(values = palette_named, name = NULL) +
        scale_linetype_manual(values = c(Mean = "solid", Median = "dashed"),
                              name = NULL) +
        scale_x_continuous(limits = c(0, x_panel), breaks = seq(0, x_panel, 50)) +
        scale_y_continuous(expand = expansion(mult = c(0.02, 0.05))) +
        guides(
            color    = guide_legend(order = 1, override.aes = list(linetype = "solid",
                                                                    linewidth = 1.0)),
            linetype = guide_legend(order = 2, override.aes = list(color = "white",
                                                                    linewidth = 0.5))
        ) +
        labs(title = "Religion Attainment Times",
             x = "Turn", y = "Density") +
        theme_fn(base_size = 12) +
        theme(legend.position = c(0.98, 0.98),
              legend.justification = c(1, 1),
              legend.background = element_rect(fill = scales::alpha(bg, 0.85),
                                               color = NA),
              legend.spacing.y = unit(2, "pt"))
}

save_plot(build_attainment(theme_report, IPSUM_VP_BG),
          "03a_religion_attainment_times", width = 12, height = 6)
save_plot_dark(build_attainment(theme_report_dark, IPSUM_VP_DARK_BG),
               "03b_religion_attainment_times", width = 12, height = 6)
