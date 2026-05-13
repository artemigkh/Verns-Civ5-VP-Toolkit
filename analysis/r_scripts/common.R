# =============================================================================
# common.R -- shared defs/utils for the Civ5 VP autoplay R report.
#
# Sourced by every vis script in analysis/r_scripts/. Loads packages,
# constants, palettes, ggplot theme, and the Spark intermediate CSVs
# (with optional bootstrap-resample augmentation controlled by
# `use_synthetic_data`).
#
# Scripts assume their working directory is `analysis/` (the parent of
# `r_scripts/`).  run_all.ps1 / run_all.sh handle that.
# =============================================================================

suppressPackageStartupMessages({
    library(readr)
    library(dplyr)
    library(tidyr)
    library(ggplot2)
    library(scales)
    library(forcats)
    library(stringr)
    library(hrbrthemes)
    library(patchwork)
    library(ggbeeswarm)
    library(ggrepel)
    library(ggridges)
    library(ggdark)
})

# -----------------------------------------------------------------------------
# SYNTHETIC: Master flag for synthetic-data augmentation.
# When TRUE, bootstrap-resample the loaded data frames so each one has at
# least SYNTH_TARGET_N rows of game-level data.  Set to FALSE for production.
# To remove later, search for "SYNTHETIC:" and delete every marked block.
# -----------------------------------------------------------------------------
use_synthetic_data <- FALSE
SYNTH_TARGET_N     <- 521
SYNTH_SEED         <- 421

OUTPUT_DIR_LIGHT <- Sys.getenv("CIV5_OUTPUT_DIR_LIGHT",
                              unset = file.path("output", "r_plots", "light"))
OUTPUT_DIR_DARK  <- Sys.getenv("CIV5_OUTPUT_DIR_DARK",
                              unset = file.path("output", "r_plots", "dark"))
dir.create(OUTPUT_DIR_LIGHT, recursive = TRUE, showWarnings = FALSE)
dir.create(OUTPUT_DIR_DARK,  recursive = TRUE, showWarnings = FALSE)

# Victory-type palette mirroring the Python report's vtc_lut. Kept as the
# legacy default; new code should pick `vtc_lut_a` (light) or `vtc_lut_b`
# (dark) explicitly.
vtc_lut <- c(
    "Cultural"          = "#e844b7",
    "Diplomatic"        = "#4DAF4A",
    "Science"           = "#386BAF",
    "Time"              = "#1a1a1a",
    "Domination"        = "#e44335",
    "Authority"         = "#ff9900",
    "Losses"            = "#9e9e9e"
)

# `vtc_lut_a` -- canonical "light" victory palette used by the `_a` variants
# of every victory-related graph.  Tuned to read well on the warm-gray
# IPSUM_VP_BG panel.
vtc_lut_a <- c(
    "Cultural"          = "#ffb8de",
    "Science"           = "#00a0a8",
    "Domination"        = "#e03e3e",
    "Diplomatic"        = "#3b0d68",
    "Time"              = vtc_lut[["Time"]],
    "Authority"         = vtc_lut[["Authority"]],
    "Losses"            = vtc_lut[["Losses"]]
)

# `vtc_lut_b` -- canonical "dark" victory palette used by the `_b` variants.
# Bright/saturated colors that pop against the dark IPSUM_VP_DARK_BG panel.
vtc_lut_b <- c(
    "Cultural"          = "#E700E7",
    "Diplomatic"        = "#6600cc",
    "Science"           = "#86f9fe",
    "Time"              = "white",
    "Domination"        = "#B22222",  # firebrick
    "Authority"         = vtc_lut[["Authority"]],
    "Losses"            = vtc_lut[["Losses"]]
)
VICTORY_LEVELS <- c("Cultural", "Science", "Domination", "Diplomatic", "Time")
VICTORY_LEVELS_AUG <- c("Cultural", "Science", "Domination",
                       "Authority", "Diplomatic", "Time")

era_lut <- c("1" = "Ancient", "2" = "Classical", "3" = "Medieval",
             "4" = "Renaissance", "5" = "Industrial", "6" = "Modern",
             "7" = "Atomic", "8" = "Information", "9" = "Future")

religion_event_lut <- c(
    "pantheon"          = "#1f77b4",
    "religion_founded"  = "#d62728",
    "religion_enhanced" = "#ff7f0e",
    "religion_reformed" = "#2ca02c"
)
religion_event_labels <- c(
    "pantheon"          = "Pantheon Founded",
    "religion_founded"  = "Religion Founded",
    "religion_enhanced" = "Religion Enhanced",
    "religion_reformed" = "Religion Reformed"
)
belief_category_lut <- c(
    "PANTHEON"    = "#1f77b4",
    "FOUNDER"     = "#d62728",
    "ENHANCER"    = "#ff7f0e",
    "FOLLOWER"    = "#9467bd",
    "REFORMATION" = "#2ca02c"
)

# -----------------------------------------------------------------------------
# Shared theme + save helper.
# -----------------------------------------------------------------------------

# Warm-gray background tuned to soften the bright in-game VP palette without
# altering any of the brand hex codes themselves. Borders/outlines use the
# same color so they blend into the panel.
IPSUM_VP_BG <- "#efece8"

# Custom variant of hrbrthemes::theme_ipsum with a warm-gray panel/plot
# background and matching-color outlines.
theme_ipsum_vp <- function(base_size = 13, axis_title_size = base_size,
                           grid = "XY", ticks = TRUE) {
    theme_ipsum(base_size = base_size, axis_title_size = axis_title_size,
                grid = grid, ticks = ticks) +
        theme(
            plot.background   = element_rect(fill = IPSUM_VP_BG, color = IPSUM_VP_BG),
            panel.background  = element_rect(fill = IPSUM_VP_BG, color = IPSUM_VP_BG),
            panel.border      = element_rect(fill = NA,           color = IPSUM_VP_BG),
            legend.background = element_rect(fill = IPSUM_VP_BG, color = IPSUM_VP_BG),
            legend.box.background = element_rect(fill = IPSUM_VP_BG, color = IPSUM_VP_BG),
            legend.key        = element_rect(fill = IPSUM_VP_BG, color = IPSUM_VP_BG),
            strip.background  = element_rect(fill = IPSUM_VP_BG, color = IPSUM_VP_BG)
        )
}

theme_report <- function(base_size = 13) {
    theme_ipsum_vp(base_size = base_size, axis_title_size = base_size,
                   grid = "XY", ticks = TRUE) +
        theme(
            plot.title         = element_text(face = "bold", size = base_size + 4),
            plot.subtitle      = element_text(color = "grey35", size = base_size),
            plot.caption       = element_text(color = "grey45", size = base_size - 3),
            plot.title.position = "plot",
            legend.position    = "top",
            legend.title       = element_text(face = "bold"),
            panel.grid.minor   = element_blank()
        )
}

save_plot <- function(p, name, width = 10, height = 7, dpi = 150) {
    path <- file.path(OUTPUT_DIR_LIGHT, paste0(name, ".png"))
    ggsave(path, p, width = width, height = height, dpi = dpi, bg = IPSUM_VP_BG)
    cat("saved:", path, "\n")
    invisible(p)
}

# -----------------------------------------------------------------------------
# Dark theme variant -- panel/plot backgrounds are a warm near-black.  Built
# on top of ggdark's `dark_theme_*` then overridden so the warm tone harmonizes
# with the bright `vtc_lut_b` palette.
# -----------------------------------------------------------------------------
IPSUM_VP_DARK_BG <- "#181614"   # warm near-black
IPSUM_VP_DARK_FG <- "#e8e4dc"   # warm light-gray for axis/text
IPSUM_VP_DARK_GRID <- "#2e2a26" # subtle gridline color

theme_ipsum_vp_dark <- function(base_size = 13, axis_title_size = base_size,
                                grid = "XY", ticks = TRUE) {
    # Build directly on theme_ipsum to inherit its typography, then flip
    # fg/bg to our warm near-black palette.  We deliberately avoid
    # ggdark::dark_mode() because it conflicts with some hrbrthemes elements.
    theme_ipsum(base_size = base_size, axis_title_size = axis_title_size,
                grid = grid, ticks = ticks) +
        theme(
            plot.background       = element_rect(fill = IPSUM_VP_DARK_BG, color = IPSUM_VP_DARK_BG),
            panel.background      = element_rect(fill = IPSUM_VP_DARK_BG, color = IPSUM_VP_DARK_BG),
            panel.border          = element_rect(fill = NA,                color = IPSUM_VP_DARK_BG),
            legend.background     = element_rect(fill = IPSUM_VP_DARK_BG, color = IPSUM_VP_DARK_BG),
            legend.box.background = element_rect(fill = IPSUM_VP_DARK_BG, color = IPSUM_VP_DARK_BG),
            legend.key            = element_rect(fill = IPSUM_VP_DARK_BG, color = IPSUM_VP_DARK_BG),
            strip.background      = element_rect(fill = IPSUM_VP_DARK_BG, color = IPSUM_VP_DARK_BG),
            panel.grid.major      = element_line(color = IPSUM_VP_DARK_GRID),
            panel.grid.minor      = element_blank(),
            axis.text             = element_text(color = IPSUM_VP_DARK_FG),
            axis.title            = element_text(color = IPSUM_VP_DARK_FG),
            plot.title            = element_text(color = IPSUM_VP_DARK_FG),
            plot.subtitle         = element_text(color = IPSUM_VP_DARK_FG),
            plot.caption          = element_text(color = IPSUM_VP_DARK_FG),
            legend.text           = element_text(color = IPSUM_VP_DARK_FG),
            legend.title          = element_text(color = IPSUM_VP_DARK_FG)
        )
}

theme_report_dark <- function(base_size = 13) {
    theme_ipsum_vp_dark(base_size = base_size, axis_title_size = base_size,
                        grid = "XY", ticks = TRUE) +
        theme(
            plot.title          = element_text(face = "bold", size = base_size + 4,
                                                color = IPSUM_VP_DARK_FG),
            plot.subtitle       = element_text(color = "grey70", size = base_size),
            plot.caption        = element_text(color = "grey60", size = base_size - 3),
            plot.title.position = "plot",
            legend.position     = "top",
            legend.title        = element_text(face = "bold",
                                                color = IPSUM_VP_DARK_FG),
            panel.grid.minor    = element_blank()
        )
}

save_plot_dark <- function(p, name, width = 10, height = 7, dpi = 150) {
    path <- file.path(OUTPUT_DIR_DARK, paste0(name, ".png"))
    ggsave(path, p, width = width, height = height, dpi = dpi,
           bg = IPSUM_VP_DARK_BG)
    cat("saved:", path, "\n")
    invisible(p)
}

# Caption-less twin: strip the bottom-right info caption so the resulting
# PNG can be stacked into a composite without doubling up captions.
# Handles both plain ggplot captions and patchwork plot_annotation captions.
save_plot_dark_nocap <- function(p, name, width = 10, height = 7, dpi = 150) {
    p <- p + labs(caption = NULL) +
        theme(plot.caption = element_blank())
    if (inherits(p, "patchwork")) {
        p <- p + patchwork::plot_annotation(
            caption = NULL,
            theme   = theme(plot.caption = element_blank())
        )
    }
    save_plot_dark(p, name, width = width, height = height, dpi = dpi)
}

# Convenience: pick the right save fn given a variant code ("a" or "b").
save_plot_variant <- function(p, name, variant = c("a", "b"),
                              width = 10, height = 7, dpi = 150) {
    variant <- match.arg(variant)
    if (variant == "a") {
        save_plot(p, name, width = width, height = height, dpi = dpi)
    } else {
        save_plot_dark(p, name, width = width, height = height, dpi = dpi)
    }
}

# -----------------------------------------------------------------------------
# Standard bottom-right caption for every report graph.
# Format: "N Autoplay Games | VP 5.2.3 | Standard Size Communitu 3.2.0 | Emperor Difficulty"
# `n` defaults to the package-loaded n_games but isn't bound at definition
# time -- callers pass their own count for filtered/derived datasets.
# -----------------------------------------------------------------------------
default_caption <- function(n = NULL) {
    if (is.null(n)) n <- get0("n_games", inherits = TRUE)
    vp_version  <- Sys.getenv("CIV5_VP_VERSION",       unset = "5.2.3")
    com_version <- Sys.getenv("CIV5_COMMUNITU_VERSION", unset = "3.2.0")
    sprintf(
        "%d Autoplay Games \u2022 VP %s \u2022 Communitu %s \u2022 Standard Size \u2022 Emperor Difficulty",
        as.integer(n), vp_version, com_version
    )
}

# Returns a `theme()` fragment styling plot.caption for the bottom-right
# corner.  `variant` picks the caption color appropriate to the panel bg.
# Dark variant uses the same grey60 as theme_report_dark's default so the
# composite caption matches the per-plot ones (e.g. "Religion Attainment
# Times").
caption_theme <- function(variant = c("a", "b")) {
    variant <- match.arg(variant)
    color <- if (variant == "b") "grey60" else "grey25"
    theme(plot.caption = element_text(color = color, size = 11,
                                      hjust = 1, face = "italic",
                                      margin = margin(t = 1, unit = "cm")))
}

# -----------------------------------------------------------------------------
# Spark intermediate CSV loader. Reads every *.csv file in the named
# subdirectory of INTERMEDIATE_CSVS (or in `name` if it's an absolute /
# relative path that already exists) and row-binds them into a single
# data frame.
# -----------------------------------------------------------------------------
INTERMEDIATE_CSVS <- Sys.getenv(
    "CIV5_INTERMEDIATE_CSVS",
    unset = file.path("..", "data", "MP_AUTOPLAY_VP_5_2_3",
                      "intermediate_csvs")
)

load_spark_csv <- function(name) {
    dir <- if (dir.exists(name)) name else file.path(INTERMEDIATE_CSVS, name)
    files <- list.files(dir, pattern = "\\.csv$", full.names = TRUE,
                        ignore.case = TRUE)
    stopifnot(length(files) >= 1)
    read_csv(files, show_col_types = FALSE, progress = FALSE)
}

# =============================================================================
# Game-level loaders (game_result + power_ranking) with SYNTHETIC augmentation.
# Stashes a mapping (.synth_src_game_ids / .synth_new_game_ids) so per-game
# tables loaded later (religion_choices, tech_completion, era_transitions,
# branch_stats) can be cloned in lock-step.
# =============================================================================
game_result_df <- load_spark_csv("game_result") %>%
    mutate(victory_type = factor(victory_type, levels = VICTORY_LEVELS))

power_ranking_df <- load_spark_csv("power_ranking")

.synth_src_game_ids <- character(0)
.synth_new_game_ids <- character(0)

if (use_synthetic_data) {
    set.seed(SYNTH_SEED)
    n_real  <- nrow(game_result_df)
    n_synth <- max(0, SYNTH_TARGET_N - n_real)
    if (n_synth > 0) {
        synth_idx <- sample.int(n_real, n_synth, replace = TRUE)
        synth_games <- game_result_df[synth_idx, ] %>%
            mutate(turn = pmax(1, round(turn + rnorm(dplyr::n(), 0, 5))))
        synth_games$game_id <- paste0("synth_", seq_len(n_synth))
        .synth_src_game_ids <- game_result_df$game_id[synth_idx]
        .synth_new_game_ids <- synth_games$game_id
        game_result_df <- bind_rows(game_result_df, synth_games)

        scale_factor <- nrow(game_result_df) / n_real
        pr_count_cols <- intersect(
            c("count_games", "wins",
              "culture_victories", "science_victories",
              "domination_victories", "diplomatic_victories", "time_victories"),
            names(power_ranking_df)
        )
        power_ranking_df <- power_ranking_df %>%
            mutate(across(all_of(pr_count_cols),
                          ~ round(suppressWarnings(as.numeric(as.character(.))) * scale_factor)))
    }
    cat("SYNTHETIC: game_result_df rows ->", nrow(game_result_df), "\n")
}

n_games <- nrow(game_result_df)

# Helper: clone rows of a per-game table for each synthetic game.
synth_clone_per_game <- function(df, label) {
    if (!use_synthetic_data || length(.synth_new_game_ids) == 0) return(df)
    synth_list <- lapply(seq_along(.synth_new_game_ids), function(i) {
        rc <- df %>% filter(game_id == .synth_src_game_ids[i])
        if (nrow(rc) == 0) return(NULL)
        rc %>% mutate(game_id = .synth_new_game_ids[i])
    })
    out <- bind_rows(df, bind_rows(synth_list))
    cat("SYNTHETIC:", label, "rows ->", nrow(out), "\n")
    out
}

# =============================================================================
# Authority-victory data + pseudo-domination derivation.
#
# In the pseudo-domination variant of the report we treat a civilization as
# winning the moment it first reaches the authority/domination threshold of
# >=66% of tiles AND cities (`pseudo_victory == 1` in authority_victories).
# Per game, the FIRST civ to hit that threshold (lowest turn) becomes the
# pseudo-domination winner and the game's effective end-turn moves up to
# that turn -- unless the recorded victory was already Domination, in which
# case we leave the row alone (a real dom win is still a dom win).
#
# `build_augmented_game_result()` returns game_result_df augmented with:
#   - victory_type_aug   factor over VICTORY_LEVELS_AUG
#   - victory_civ_aug    chr (civ that wins under the pseudo-dom rule)
#   - turn_aug           int (effective game-ending turn; <= original turn)
# =============================================================================
load_authority_victories_df <- function() {
    av <- load_spark_csv("authority_victories")
    synth_clone_per_game(av, "authority_victories_df")
}

build_augmented_game_result <- function(authority_victories_df = NULL) {
    if (is.null(authority_victories_df)) {
        authority_victories_df <- load_authority_victories_df()
    }
    # First civ to cross the 66% threshold per game (earliest turn wins).
    first_hit <- authority_victories_df %>%
        filter(pseudo_victory == 1) %>%
        group_by(game_id) %>%
        slice_min(turn, n = 1, with_ties = FALSE) %>%
        ungroup() %>%
        select(game_id, pd_civ = owner_nation, pd_turn = turn)

    game_result_df %>%
        left_join(first_hit, by = "game_id") %>%
        mutate(
            # Apply the pseudo-dom override whenever:
            #   (a) some civ actually crossed 66%, and
            #   (b) it happened on/before the recorded game-ending turn.
            # Domination wins are NOT exempt: if an authority-threshold
            # crossing predates the dom victory (even by the same civ),
            # the game is reclassified as an Authority/pseudo-dom win.
            apply_pd = !is.na(pd_civ) &
                       !is.na(pd_turn) &
                       pd_turn <= turn,
            victory_type_aug = factor(
                ifelse(apply_pd, "Authority",
                       as.character(victory_type)),
                levels = VICTORY_LEVELS_AUG
            ),
            victory_civ_aug = ifelse(apply_pd, pd_civ,  victory_civ),
            turn_aug        = as.integer(ifelse(apply_pd, pd_turn, turn))
        ) %>%
        select(-apply_pd)
}

# =============================================================================
# Religion data (loaded lazily on demand).
# =============================================================================
load_religion_data <- function() {
    rc <- load_spark_csv("religion_choices") %>%
        left_join(game_result_df %>% select(game_id, civ = victory_civ, victory_type),
                  by = c("game_id", "civ")) %>%
        mutate(win = ifelse(!is.na(victory_type), 1L, 0L))
    rc <- synth_clone_per_game(rc, "religion_choices_df")

    belief_categories <- rc %>%
        distinct(belief, type) %>%
        group_by(belief) %>%
        summarise(types = paste(sort(unique(type)), collapse = "|"),
                  .groups = "drop") %>%
        mutate(category = case_when(
            types == "pantheon"                              ~ "PANTHEON",
            types == "religion_reformed"                     ~ "REFORMATION",
            types == "religion_founded"                      ~ "FOUNDER",
            types == "religion_enhanced"                     ~ "ENHANCER",
            types == "religion_enhanced|religion_founded"    ~ "FOLLOWER",
            TRUE                                             ~ "OTHER"
        )) %>%
        select(belief, category)

    list(choices = rc, categories = belief_categories)
}

# =============================================================================
# Belief plot helpers (used by 04..07).
# =============================================================================
belief_pick_stats <- function(choices_df, event_types, belief_categories) {
    choices_df %>%
        filter(type %in% event_types) %>%
        group_by(belief) %>%
        summarise(chosen_count = dplyr::n(),
                  wins         = sum(win),
                  avg_turn     = mean(turn),
                  .groups      = "drop") %>%
        mutate(winrate = wins / chosen_count) %>%
        left_join(belief_categories, by = "belief")
}

plot_belief_freq_perf <- function(stats_df,
                                  title,
                                  caption = NULL,
                                  color_by_category = FALSE,
                                  category_palette = belief_category_lut,
                                  show_category_legend = FALSE,
                                  theme_fn = theme_report,
                                  text_color = "grey25",
                                  segment_color = "grey75",
                                  point_outline = "grey25") {
    df <- stats_df %>%
        mutate(belief = forcats::fct_reorder(belief, chosen_count))

    p <- ggplot(df, aes(x = chosen_count, y = belief)) +
        geom_segment(aes(x = 0, xend = chosen_count, yend = belief),
                     color = segment_color, linewidth = 0.5)

    if (color_by_category) {
        cat_guide <- if (show_category_legend) "legend" else "none"
        p <- p +
            geom_point(aes(size = chosen_count, fill = category),
                       shape = 21, color = point_outline, stroke = 0.4) +
            scale_fill_manual(values = category_palette,
                              name = "Category", drop = FALSE,
                              guide = cat_guide)
    } else {
        wr_max <- max(df$winrate, 0.25, na.rm = TRUE)
        wr_lim <- c(0, max(wr_max, 0.25))
        p <- p +
            geom_point(aes(size = chosen_count, fill = winrate),
                       shape = 21, color = point_outline, stroke = 0.4) +
            scale_fill_gradient2(
                low = "#b30000", mid = "#f7f7f7",
                high = "#1a9850", midpoint = 0.125,
                limits = wr_lim,
                labels = percent_format(accuracy = 1),
                breaks = c(0, 0.125, wr_lim[2]),
                name = "Win rate",
                guide = guide_colourbar(
                    title.position = "left", title.vjust = 0.95,
                    barwidth  = unit(40, "lines"),
                    barheight = unit(0.7, "lines"),
                    frame.colour = NA,
                    ticks = FALSE
                )
            )
    }

    p <- p +
        geom_text(aes(label = sprintf("%d  (%s)", chosen_count,
                                      percent(winrate, accuracy = 1))),
                  hjust = 0, nudge_x = 7,
                  size = 4.5, color = text_color) +
        scale_size_continuous(range = c(3, 13), guide = "none") +
        scale_x_continuous(expand = expansion(mult = c(0.02, 0.40))) +
        labs(title = title, caption = caption,
             x = "Times chosen", y = NULL) +
        theme_fn(base_size = 18) +
        theme(panel.grid.major.y = element_blank())

    if (color_by_category) {
        p <- if (show_category_legend) p + theme(legend.position = "top")
             else                       p + theme(legend.position = "none")
    } else {
        legend_label_col <- if (identical(theme_fn, theme_report_dark)) "grey75" else "grey45"
        p <- p + theme(
            legend.position   = "bottom",
            legend.direction  = "horizontal",
            legend.justification = "center",
            legend.box.just      = "center",
            legend.title      = element_text(size = 14, color = legend_label_col,
                                             face = "plain"),
            legend.text       = element_text(size = 12, color = legend_label_col),
            legend.margin     = margin(t = 4, r = 0, b = 0, l = 0),
            legend.box.margin = margin(t = -2, r = 0, b = 0, l = 0),
            legend.background = element_rect(fill = NA, color = NA),
            legend.key        = element_rect(fill = NA, color = NA)
        )
    }
    p
}

# Stacked-bar variant of plot_belief_freq_perf: green = wins, red = losses,
# rows ordered by total pick count (chosen_count = wins + losses) ascending
# so the largest sits at the top of a flipped/horizontal bar plot.
plot_belief_winloss_stack <- function(stats_df, title, caption = NULL,
                                      theme_fn = theme_report,
                                      text_color = "grey25",
                                      bar_outline = "grey25") {
    df <- stats_df %>%
        mutate(losses = chosen_count - wins,
               belief = forcats::fct_reorder(belief, chosen_count))

    long_df <- df %>%
        select(belief, chosen_count, winrate, wins, losses) %>%
        tidyr::pivot_longer(c(wins, losses),
                            names_to = "outcome", values_to = "count") %>%
        mutate(outcome = factor(outcome, levels = c("wins", "losses")))

    label_df <- df %>%
        mutate(label = sprintf("%d  (%s)", chosen_count,
                               percent(winrate, accuracy = 1)))

    ggplot(long_df, aes(x = count, y = belief, fill = outcome)) +
        geom_col(width = 0.78, color = bar_outline, linewidth = 0.3) +
        geom_text(data = label_df,
                  aes(x = chosen_count, y = belief, label = label),
                  inherit.aes = FALSE,
                  hjust = 0, nudge_x = max(df$chosen_count) * 0.01 + 5,
                  size = 5.4, color = text_color) +
        scale_fill_manual(values = c(wins = "#1a9850", losses = "#b30000"),
                          labels = c(wins = "Wins", losses = "Losses"),
                          breaks = c("losses", "wins"),
                          name = NULL) +
        scale_x_continuous(expand = expansion(mult = c(0.01, 0.18))) +
        labs(title = title, caption = caption,
             x = "Times chosen", y = NULL) +
        theme_fn(base_size = 18) +
        theme(panel.grid.major.y = element_blank(),
              legend.position    = "top",
              legend.justification = "left")
}

# Ridgeline variant: y = belief (ordered by pick count, asc, like the
# winloss stack), x = distribution of turn at which the belief was picked.
# `picks_df` is the raw, filtered religion_choices subset (pre-aggregation)
# for the desired event type(s) and belief subset; `stats_df` provides the
# pick-count ordering.
plot_belief_turn_ridge <- function(picks_df, stats_df, title, caption = NULL,
                                   theme_fn = theme_report,
                                   bg = IPSUM_VP_BG,
                                   viridis_opt = "viridis",
                                   begin = 0, end = 1,
                                   vline_color = "white") {
    belief_levels <- stats_df %>%
        arrange(chosen_count) %>% pull(belief)

    df <- picks_df %>%
        filter(belief %in% belief_levels) %>%
        mutate(belief = factor(belief, levels = belief_levels))

    turn_range <- c(0, as.numeric(quantile(df$turn, 0.99, na.rm = TRUE)))
    if (!is.finite(turn_range[2]) || turn_range[2] <= 0) {
        turn_range <- c(0, max(df$turn, na.rm = TRUE))
    }

    ggplot(df, aes(x = turn, y = belief, fill = after_stat(x))) +
        geom_density_ridges_gradient(
            scale = 2.0, rel_min_height = 0.01,
            color = bg, linewidth = 0.4,
            quantile_lines = TRUE, quantiles = 0.5,
            vline_color = vline_color,
            vline_linetype = "dotted", vline_width = 0.8
        ) +
        scale_fill_viridis_c(option = viridis_opt, limits = turn_range,
                             oob = scales::squish,
                             begin = begin, end = end, guide = "none") +
        scale_x_continuous(limits = turn_range,
                           expand = expansion(mult = c(0.01, 0.05))) +
        labs(title = title, caption = caption,
             x = "Turn picked", y = NULL) +
        theme_fn(base_size = 18) +
        theme(panel.grid.major.y = element_blank())
}
