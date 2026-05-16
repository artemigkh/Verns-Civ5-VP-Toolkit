# 04: Pseudo-domination version of the winrate-by-civ stacked bars.
# Same structure as 02 (denominators = `count_games` from power_ranking_df,
# numerators per type from power_ranking_df vtype_cols), but each
# "pseudo-dom event" -- a game where some civ first reached the >=66%
# tiles+cities authority threshold on or before the game-ending turn --
# shifts ONE win:
#   -1 from (recorded_victor, recorded_type)
#   +1 to   (first-to-66%-civ, "Authority")
#
# Domination wins are NOT exempt: if an authority-threshold crossing
# predates (or matches) the dom victory, the win is reclassified as
# Authority -- matching the rule used by `build_augmented_game_result()`
# in common.R (and hence by script 03).
#
# Effects:
#   * winrates per civ may rise OR fall vs script 02 (a civ can lose a
#     "real" win that gets relabelled, or steal one from another civ).
#   * total wins per game still sum to 1, so totals across civs are
#     unchanged; only the distribution shifts.
#
# Produces:
#   04a_pseudo_dom_winrate_by_civ.png   light theme + vtc_lut_a
#   04b_pseudo_dom_winrate_by_civ.png   dark theme  + vtc_lut_b
source("r_scripts/common.R")

vtype_cols <- c(
    "culture_victories",
    "science_victories",
    "domination_victories",
    "diplomatic_victories",
    "time_victories"
)
raw_to_label <- c(
    culture_victories    = "Cultural",
    science_victories    = "Science",
    domination_victories = "Domination",
    diplomatic_victories = "Diplomatic",
    time_victories       = "Time"
)

# Per-game first-to-66% events that actually displace the recorded winner.
authority_victories_df <- load_authority_victories_df()

first_hit <- authority_victories_df %>%
    filter(pseudo_victory == 1) %>%
    group_by(game_id) %>%
    slice_min(turn, n = 1, with_ties = FALSE) %>%
    ungroup() %>%
    select(game_id, pd_civ = owner_nation, pd_turn = turn)

shift_events <- game_result_df %>%
    inner_join(first_hit, by = "game_id") %>%
    filter(pd_turn <= turn) %>%
    transmute(orig_civ = victory_civ,
              orig_type = as.character(victory_type),
              pd_civ)

# (orig_civ, orig_type) -> count of wins to remove.
remove_df <- shift_events %>%
    count(civ = orig_civ, victory_type = orig_type, name = "remove")

# (pd_civ) -> count of new Authority wins to add.
add_df <- shift_events %>%
    count(civ = pd_civ, name = "add") %>%
    mutate(victory_type = "Authority")

# Long-form wins per (civ, type), starting from power_ranking_df.
games_per_civ <- power_ranking_df %>%
    transmute(civ, count_games = as.numeric(count_games))

wins_long <- power_ranking_df %>%
    mutate(across(all_of(vtype_cols),
                  ~ suppressWarnings(as.numeric(as.character(.))) %>% replace_na(0))) %>%
    select(civ, all_of(vtype_cols)) %>%
    pivot_longer(all_of(vtype_cols),
                 names_to = "vtype_raw", values_to = "wins") %>%
    mutate(victory_type = unname(raw_to_label[vtype_raw])) %>%
    select(civ, victory_type, wins)

# Apply removals.
wins_long <- wins_long %>%
    left_join(remove_df, by = c("civ", "victory_type")) %>%
    mutate(wins = pmax(0, wins - replace_na(remove, 0))) %>%
    select(-remove)

# Append Authority rows for every civ (filled with 0, then add).
pseudo_long <- games_per_civ %>%
    transmute(civ,
              victory_type = "Authority",
              wins = 0) %>%
    left_join(add_df %>% select(civ, add), by = "civ") %>%
    mutate(wins = wins + replace_na(add, 0)) %>%
    select(civ, victory_type, wins)

winrate_long <- bind_rows(wins_long, pseudo_long) %>%
    inner_join(games_per_civ, by = "civ") %>%
    mutate(victory_type = factor(victory_type, levels = VICTORY_LEVELS_AUG),
           share_winrate = ifelse(count_games > 0, wins / count_games, 0))

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

caption_text <- sprintf(
    "%d completed Civ5 VP autoplay games  -  Emperor difficulty",
    n_games)

build_winrate <- function(lut, bg, theme_fn, text_color, ref_text_color,
                          caption_color) {
    ggplot(winrate_long,
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
        scale_fill_manual(values = lut, name = "Victory type", drop = FALSE) +
        scale_y_continuous(labels = percent_format(accuracy = 1),
                           expand = expansion(mult = c(0, 0.10))) +
        labs(title = "Win Rate By Civilization",
             caption = caption_text,
             x = "Civilization", y = "Win rate") +
        theme_fn(base_size = 12) +
        theme(
            axis.text.x        = element_text(angle = 45, hjust = 1, vjust = 1, size = 9),
            panel.grid.major.x = element_blank(),
            plot.caption       = element_text(color = caption_color, size = 11,
                                              hjust = 1, face = "italic")
        )
}

save_plot(
    build_winrate(vtc_lut_a, IPSUM_VP_BG, theme_report,
                  text_color = "grey25", ref_text_color = "grey20",
                  caption_color = "grey25"),
    "04a_pseudo_dom_winrate_by_civ", width = 14, height = 7)

save_plot_dark(
    build_winrate(vtc_lut_b, IPSUM_VP_DARK_BG, theme_report_dark,
                  text_color = IPSUM_VP_DARK_FG, ref_text_color = "grey75",
                  caption_color = IPSUM_VP_DARK_FG),
    "04b_pseudo_dom_winrate_by_civ", width = 14, height = 7)
