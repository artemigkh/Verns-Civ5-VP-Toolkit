# debug_science_future_turns.R
# Diagnostic: 5-panel row (4 shared y-axis + 1 independent delta).
#   1. Science victory game-ending turns  (source data: 01b)
#   2. Turn entering Future Era, all civs (source data: 12b)
#   3. Turn entering Future Era, science-victory civs only (game_result filter)
#   4. First turn any civ researches TECH_FUTURE_TECH (technology_completion_records)
#   5. (delta) SV turn minus Future Era entry turn, sci victors only (independent axis)
source("r_scripts/common.R")

# ---------------------------------------------------------------------------
# 1. Science victory game-ending turns -- same data as the 01b violin
# ---------------------------------------------------------------------------
sci_victory_turns <- game_result_df %>%
    filter(victory_type == "Science") %>%
    transmute(turn = turn, label = "Science\nVictory Turn")

# ---------------------------------------------------------------------------
# 2. Future Era entry turn -- all civ instances (same derivation as 12b)
# ---------------------------------------------------------------------------
era_transitions_df <- load_spark_csv("era_transitions") %>%
    mutate(era = as.integer(era))
era_transitions_df <- synth_clone_per_game(era_transitions_df, "era_transitions_df")

future_era_all <- era_transitions_df %>%
    filter(era == 9) %>%
    group_by(game_id, civ) %>%
    summarise(turn = min(turn), .groups = "drop") %>%
    transmute(turn = turn, label = "All Spaceship\nTechs Completed")

# ---------------------------------------------------------------------------
# 3. Future Era entry turn -- only civ instances that won via Science
# ---------------------------------------------------------------------------
sci_winners <- game_result_df %>%
    filter(science_victory == 1) %>%
    select(game_id, civ = victory_civ)

future_era_sci <- era_transitions_df %>%
    filter(era == 9) %>%
    group_by(game_id, civ) %>%
    summarise(turn = min(turn), .groups = "drop") %>%
    semi_join(sci_winners, by = c("game_id", "civ")) %>%
    transmute(turn = turn, label = "All Spaceship Techs\nCompleted\n(Sci Victors Only)")

# ---------------------------------------------------------------------------
# 3b. Raw join for panel 5: SV turn - Future Era entry turn (sci victors only)
# ---------------------------------------------------------------------------
sci_winner_turns <- game_result_df %>%
    filter(science_victory == 1) %>%
    select(game_id, civ = victory_civ, sv_turn = turn)

delta_sv_spaceship <- era_transitions_df %>%
    filter(era == 9) %>%
    group_by(game_id, civ) %>%
    summarise(era_turn = min(turn), .groups = "drop") %>%
    inner_join(sci_winner_turns, by = c("game_id", "civ")) %>%
    transmute(turn = sv_turn - era_turn,
              label = "Turns to SV After\nSpaceship Techs\nCompleted")

# ---------------------------------------------------------------------------
# 4. First turn a civ researches TECH_FUTURE_TECH within a game
# ---------------------------------------------------------------------------
tech_df <- load_spark_csv("technology_completion_records")
tech_df <- synth_clone_per_game(tech_df, "technology_completion_records")

future_tech_turns <- tech_df %>%
    filter(tech == "TECH_FUTURE_TECH") %>%
    group_by(game_id, nation) %>%
    summarise(turn = min(end_turn), .groups = "drop") %>%
    transmute(turn = turn, label = "First Future Tech\nCompleted Turn")

# ---------------------------------------------------------------------------
# Shared y-axis range for panels 1-4 (rounded to nearest 25)
# ---------------------------------------------------------------------------
all_turns <- c(sci_victory_turns$turn, future_era_all$turn,
               future_era_sci$turn,    future_tech_turns$turn)
y_lo <- floor(min(all_turns,  na.rm = TRUE) / 25) * 25
y_hi <- ceiling(max(all_turns, na.rm = TRUE) / 25) * 25

# Independent y-axis range for panel 5 (delta; rounded to nearest 5)
delta_lo <- floor(min(delta_sv_spaceship$turn,  na.rm = TRUE) / 5) * 5
delta_hi <- ceiling(max(delta_sv_spaceship$turn, na.rm = TRUE) / 5) * 5

# ---------------------------------------------------------------------------
# Panel builder
# ---------------------------------------------------------------------------
BEE_OUTLINE <- "black"

make_panel <- function(df, show_y_axis = FALSE, fill_color = vtc_lut_b[["Science"]]) {
    p <- ggplot(df, aes(x = label, y = turn)) +
        geom_violin(trim = TRUE, alpha = 0.80, fill = fill_color,
                    color = IPSUM_VP_DARK_BG, linewidth = 0.45,
                    scale = "width") +
        geom_quasirandom(shape = 21, fill = fill_color, color = BEE_OUTLINE,
                         stroke = 0.5, width = 0.25, size = 2.0,
                         alpha = 0.85) +
        scale_y_continuous(limits = c(y_lo, y_hi), labels = comma) +
        labs(x = NULL, y = if (show_y_axis) "Turn" else NULL) +
        theme_report_dark(base_size = 12) +
        theme(panel.grid.major.x = element_blank(),
              axis.text.x = element_text(color = "white"))
    if (!show_y_axis) {
        p <- p + theme(axis.text.y  = element_blank(),
                       axis.ticks.y = element_blank())
    }
    p
}

p1 <- make_panel(sci_victory_turns,  show_y_axis = TRUE)                      # science blue
p2 <- make_panel(future_era_all,     fill_color = "#ff9900")                  # orange
p3 <- make_panel(future_era_sci,     fill_color = "#e03e3e")                  # red
p4 <- make_panel(future_tech_turns,  fill_color = "grey75")                   # light grey

# Panel 5: independent axis -- delta turns (SV turn - spaceship techs turn)
FILL_P5 <- "#b388ff"  # light purple
p5 <- ggplot(delta_sv_spaceship, aes(x = label, y = turn)) +
    geom_violin(trim = TRUE, alpha = 0.80, fill = FILL_P5,
                color = IPSUM_VP_DARK_BG, linewidth = 0.45,
                scale = "width") +
    geom_quasirandom(shape = 21, fill = FILL_P5, color = BEE_OUTLINE,
                     stroke = 0.5, width = 0.25, size = 2.0,
                     alpha = 0.85) +
    scale_y_continuous(limits = c(delta_lo, delta_hi), labels = comma) +
    labs(x = NULL, y = "\u0394 Turns") +
    theme_report_dark(base_size = 12) +
    theme(panel.grid.major.x = element_blank(),
          axis.text.x = element_text(color = "white"))

# ---------------------------------------------------------------------------
# Combine with patchwork
# ---------------------------------------------------------------------------
combined <- (p1 | p2 | p3 | p4 | p5) +
    plot_layout(ncol = 5) +
    plot_annotation(
        title   = "Science Victory & Future Era/Tech Turn Diagnostics",
        caption = default_caption(),
        theme   = theme_report_dark(base_size = 13) +
            theme(plot.caption = element_text(color = "grey60", size = 10,
                                              hjust = 1, face = "italic"))
    )

save_plot_dark(combined, "debug_science_future_turns", width = 20, height = 7)

# ---------------------------------------------------------------------------
# Standalone: panel 5 only
# ---------------------------------------------------------------------------
p5_standalone <- p5 +
    labs(title = "Turns to SV After Spaceship Techs Completed",
         caption = default_caption()) +
    theme(plot.title   = element_text(face = "bold", size = 15,
                                      color = IPSUM_VP_DARK_FG),
          plot.caption = element_text(color = "grey60", size = 10,
                                      hjust = 1, face = "italic"))

save_plot_dark(p5_standalone, "debug_sv_delta_standalone", width = 6, height = 7)
