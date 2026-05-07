# 17: Religious-action attainment among winning civs - mutually exclusive
# decompositions of the 4 actions, laid out as a 2-row compound:
#   Row 1: Founded a Pantheon (only)        |  Founded a Religion (only)
#   Row 2: Enhanced only | Reformed only | Enhanced + Reformed
#
# "(only)" categories are mutually exclusive on the religious-action axis,
# so a single winning civ contributes to at most one of the bottom-row
# donuts and at most one of the top-row donuts.
#
# Green slice = winning civ matched the condition.
# Red slice   = winning civ did NOT match the condition.
# Total       = total number of winning civs.
#
# Produces:
#   17a_winner_religion_action_donuts.png  light theme
#   17b_winner_religion_action_donuts.png  dark theme
source("r_scripts/common.R")

# --- Detect bad religion logs. ---------------------------------------------
# A complete game logs exactly 8 pantheon entries (one per founding civ).
# We treat a game as unusable for this analysis if either:
#   (a) it has != 8 rows of type=="pantheon" in religion_choices
#       (covers truncation AND games with zero religion_choices rows), OR
#   (b) the civ roster in religion_choices doesn't match the civ roster
#       in civ_choices (game_id collision between independent runs).
religion_choices_df <- load_spark_csv("religion_choices")
religion_choices_df <- synth_clone_per_game(religion_choices_df, "religion_choices_df")
civ_choices_df_raw  <- load_spark_csv("civ_choices")
civ_choices_df_raw  <- synth_clone_per_game(civ_choices_df_raw, "civ_choices_df_raw")

# Universe of game_ids we care about: anything that produced a result.
all_real_ids <- unique(game_result_df$game_id)

pantheon_counts <- religion_choices_df %>%
    filter(type == "pantheon") %>%
    count(game_id, name = "n_pantheon")
pantheon_counts <- tibble::tibble(game_id = all_real_ids) %>%
    left_join(pantheon_counts, by = "game_id") %>%
    mutate(n_pantheon = ifelse(is.na(n_pantheon), 0L, n_pantheon))

# Roster comparison: for each game compare set of civs in civ_choices vs
# civs in religion_choices (any row, not just pantheon).
cc_rosters <- civ_choices_df_raw %>%
    filter(game_id %in% all_real_ids) %>%
    distinct(game_id, civ) %>%
    group_by(game_id) %>%
    summarise(cc_civs = list(sort(civ)), .groups = "drop")
rc_rosters <- religion_choices_df %>%
    filter(game_id %in% all_real_ids) %>%
    distinct(game_id, civ) %>%
    group_by(game_id) %>%
    summarise(rc_civs = list(sort(civ)), .groups = "drop")
roster_check <- cc_rosters %>%
    left_join(rc_rosters, by = "game_id") %>%
    rowwise() %>%
    mutate(
        rc_n        = length(rc_civs %||% character(0)),
        # mismatch = religion roster present and not a subset of cc roster.
        roster_mismatch = rc_n > 0 &&
                          length(setdiff(rc_civs, cc_civs)) > 0
    ) %>%
    ungroup() %>%
    select(game_id, roster_mismatch)

bad_df <- pantheon_counts %>%
    left_join(roster_check, by = "game_id") %>%
    mutate(
        roster_mismatch = ifelse(is.na(roster_mismatch), FALSE, roster_mismatch),
        bad_pantheon    = n_pantheon != 8,
        bad             = bad_pantheon | roster_mismatch
    ) %>%
    filter(bad) %>%
    arrange(n_pantheon, game_id)

cat(sprintf("Bad religion logs: %d games\n", nrow(bad_df)))
cat(sprintf("  - %d with n_pantheon != 8\n",
            sum(bad_df$bad_pantheon)))
cat(sprintf("  - %d with roster mismatch (game_id collision)\n",
            sum(bad_df$roster_mismatch)))
print(as.data.frame(bad_df %>% select(game_id, n_pantheon, roster_mismatch)),
      row.names = FALSE)
bad_ids <- bad_df$game_id

civ_choices_df <- civ_choices_df_raw

# Drop bad games from both civ_choices and game_result before any
# aggregation, so they don't contaminate the secular / mutually-exclusive
# counts.
civ_choices_df  <- civ_choices_df  %>% filter(!game_id %in% bad_ids)
game_result_df  <- game_result_df  %>% filter(!game_id %in% bad_ids)

# Restrict to the winner of each completed game (one row per won game).
winner_choices <- civ_choices_df %>%
    inner_join(
        game_result_df %>%
            filter(!is.na(victory_civ), !is.na(victory_type)) %>%
            select(game_id, victory_civ),
        by = c("game_id", "civ" = "victory_civ")
    )

n_wins <- nrow(winner_choices)

# Empty CSV cells parse to NA (or "" depending on reader); treat both as "no".
did <- function(col) !is.na(col) & nzchar(as.character(col))

w <- winner_choices %>%
    mutate(
        has_pan  = did(pantheon_founded),
        has_fnd  = did(religion_founded),
        has_enh  = did(religion_enhanced),
        has_ref  = did(religion_reformed)
    )

# Mutually exclusive condition definitions.
yes_pantheon_only       <- with(w,  has_pan & !has_fnd & !has_enh & !has_ref)
yes_founded_only        <- with(w,  has_fnd & !has_enh & !has_ref)
yes_enhanced_only       <- with(w,  has_enh & !has_ref)
yes_reformed_only       <- with(w, !has_enh &  has_ref)
yes_enhanced_reformed   <- with(w,  has_enh &  has_ref)

panel_specs <- list(
    list(label = "Founded a Pantheon (only)",       yes = sum(yes_pantheon_only)),
    list(label = "Founded a Religion (only)",       yes = sum(yes_founded_only)),
    list(label = "Enhanced a Religion",      yes = sum(yes_enhanced_only)),
    list(label = "Reformed a Religion",      yes = sum(yes_reformed_only)),
    list(label = "Enhanced + Reformed a Religion",  yes = sum(yes_enhanced_reformed))
)
for (i in seq_along(panel_specs)) {
    panel_specs[[i]]$no <- n_wins - panel_specs[[i]]$yes
}

# --- Donut geometry (cartesian; coord_polar not used). ----------------------
make_slice <- function(theta0, theta1, r_in, r_out, n = 80) {
    th_out <- seq(theta0, theta1, length.out = n)
    th_in  <- rev(th_out)
    data.frame(
        x = c(r_out * cos(th_out), r_in * cos(th_in)),
        y = c(r_out * sin(th_out), r_in * sin(th_in))
    )
}

r_in  <- 0.60
r_out <- 1.00

build_donut_polys <- function(yes_count, no_count) {
    total <- yes_count + no_count
    if (total <= 0) return(NULL)
    p_yes <- yes_count / total
    yes_theta0 <- pi/2
    yes_theta1 <- pi/2 - 2*pi * p_yes
    no_theta0  <- yes_theta1
    no_theta1  <- pi/2 - 2*pi

    bind_rows(
        if (yes_count > 0) {
            sl <- make_slice(yes_theta0, yes_theta1, r_in, r_out)
            sl$outcome <- "Yes"
            sl
        },
        if (no_count > 0) {
            sl <- make_slice(no_theta0, no_theta1, r_in, r_out)
            sl$outcome <- "No"
            sl
        }
    )
}

FILL_YES <- "#1a9850"
FILL_NO  <- "#b30000"

build_donut_panel <- function(yes_count, no_count, title_text,
                              bg, label_color, show_legend = FALSE) {
    polys <- build_donut_polys(yes_count, no_count)
    polys$outcome <- factor(polys$outcome, levels = c("Yes", "No"))
    total   <- yes_count + no_count
    pct_yes <- if (total > 0) yes_count / total else 0
    center_label <- sprintf("%s\n(%d / %d wins)",
                            percent(pct_yes, accuracy = 1),
                            yes_count, total)

    ggplot() +
        geom_polygon(data = polys,
                     aes(x = x, y = y, group = outcome, fill = outcome),
                     color = bg, linewidth = 0.6) +
        annotate("text", x = 0, y = 0, label = center_label,
                 size = 5.0, fontface = "bold", lineheight = 1.0,
                 color = label_color) +
        scale_fill_manual(values = c("Yes" = FILL_YES, "No" = FILL_NO),
                          breaks = c("Yes", "No"),
                          labels = c("Yes" = "Matched condition",
                                     "No"  = "Did not match"),
                          name   = NULL,
                          drop   = FALSE) +
        coord_fixed(xlim = c(-1.25, 1.25), ylim = c(-1.25, 1.25),
                    clip = "off") +
        labs(title = title_text) +
        theme_void(base_family = "") +
        theme(
            plot.background = element_rect(fill = bg, color = bg),
            plot.title  = element_text(face = "bold", size = 15, hjust = 0.5,
                                       color = label_color),
            plot.margin = margin(10, 15, 10, 15),
            legend.position = if (show_legend) "bottom" else "none",
            legend.text       = element_text(color = label_color, size = 12),
            legend.background = element_rect(fill = bg, color = bg),
            legend.key        = element_rect(fill = bg, color = bg)
        )
}

build_compound <- function(bg, label_color, theme_fn) {
    panels <- lapply(seq_along(panel_specs), function(i) {
        sp <- panel_specs[[i]]
        # Show legend on the last (bottom-right) panel.
        build_donut_panel(sp$yes, sp$no, sp$label, bg, label_color,
                          show_legend = (i == length(panel_specs)))
    })

    annotation_theme <- theme_fn(base_size = 13) +
        theme(plot.title      = element_text(face = "bold", size = 20,
                                             color = label_color, hjust = 0.5),
              plot.caption    = element_text(color = label_color, size = 11,
                                             hjust = 1, face = "italic"),
              plot.background = element_rect(fill = bg, color = bg))
    caption_text <- ""

    # 5 panels: top row = Pantheon-only | Founded-only;
    # bottom row = Enhanced-only | Reformed-only | Enhanced+Reformed.
    top_row    <- panels[[1]] + panels[[2]] +
                  patchwork::plot_layout(ncol = 2)
    bottom_row <- panels[[3]] + panels[[4]] + panels[[5]] +
                  patchwork::plot_layout(ncol = 3)

    (top_row / bottom_row) +
        plot_annotation(
            title   = "Religious Attainment Among Winning Civs",
            caption = caption_text,
            theme   = annotation_theme
        )
}

plot_a <- build_compound(IPSUM_VP_BG, "grey25", theme_report)
save_plot(plot_a, "17a_winner_religion_action_donuts_exclusive",
          width = 15, height = 11)

plot_b <- build_compound(IPSUM_VP_DARK_BG, IPSUM_VP_DARK_FG, theme_report_dark)
save_plot_dark(plot_b, "17b_winner_religion_action_donuts_exclusive",
               width = 15, height = 11)
