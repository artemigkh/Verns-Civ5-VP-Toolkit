# 16: Religious-action attainment among winning civs.
# Four donuts (2x2): for each game's winning civ, what fraction of those
# winners founded a Pantheon / founded a Religion / enhanced a Religion /
# reformed a Religion. The green slice = action happened, the red slice =
# the civ won without that action.
# Produces:
#   16a_winner_religion_action_donuts.png  light theme
#   16b_winner_religion_action_donuts.png  dark theme
source("r_scripts/common.R")

civ_choices_df <- load_spark_csv("civ_choices")
civ_choices_df <- synth_clone_per_game(civ_choices_df, "civ_choices_df")

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
did_action <- function(col) !is.na(col) & nzchar(as.character(col))

action_specs <- tibble::tribble(
    ~key,                ~label,
    "pantheon_founded",  "Founded a Pantheon",
    "religion_founded",  "Founded a Religion",
    "religion_enhanced", "Enhanced a Religion",
    "religion_reformed", "Reformed a Religion"
)

action_counts <- action_specs %>%
    rowwise() %>%
    mutate(yes = sum(did_action(winner_choices[[key]])),
           no  = n_wins - yes) %>%
    ungroup()

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

    p <- ggplot() +
        geom_polygon(data = polys,
                     aes(x = x, y = y, group = outcome, fill = outcome),
                     color = bg, linewidth = 0.6) +
        annotate("text", x = 0, y = 0, label = center_label,
                 size = 5.0, fontface = "bold", lineheight = 1.0,
                 color = label_color) +
        scale_fill_manual(values = c("Yes" = FILL_YES, "No" = FILL_NO),
                          breaks = c("Yes", "No"),
                          labels = c("Yes" = "Action taken",
                                     "No"  = "Action not taken"),
                          name   = NULL,
                          drop   = FALSE) +
        coord_fixed(xlim = c(-1.25, 1.25), ylim = c(-1.25, 1.25),
                    clip = "off") +
        labs(title = title_text) +
        theme_void(base_family = "") +
        theme(
            plot.background = element_rect(fill = bg, color = bg),
            plot.title  = element_text(face = "bold", size = 16, hjust = 0.5,
                                       color = label_color),
            plot.margin = margin(10, 20, 10, 20),
            legend.position = if (show_legend) "bottom" else "none",
            legend.text       = element_text(color = label_color, size = 12),
            legend.background = element_rect(fill = bg, color = bg),
            legend.key        = element_rect(fill = bg, color = bg)
        )
    p
}

build_compound <- function(bg, label_color, theme_fn) {
    panels <- mapply(function(yes, no, lbl, idx) {
        # Show the legend on the bottom-right panel only.
        build_donut_panel(yes, no, lbl, bg, label_color,
                          show_legend = (idx == 4))
    }, action_counts$yes, action_counts$no, action_counts$label,
       seq_len(nrow(action_counts)), SIMPLIFY = FALSE)

    annotation_theme <- theme_fn(base_size = 13) +
        theme(plot.title      = element_text(face = "bold", size = 20,
                                             color = label_color, hjust = 0.5),
              plot.caption    = element_text(color = label_color, size = 11,
                                             hjust = 1, face = "italic"),
              plot.background = element_rect(fill = bg, color = bg))
    caption_text <- sprintf(
        "Across %d winning civs from completed Civ5 VP autoplay games", n_wins)

    (panels[[1]] | panels[[2]]) / (panels[[3]] | panels[[4]]) +
        plot_annotation(
            title   = "Religious Actions Among Winning Civs",
            caption = caption_text,
            theme   = annotation_theme
        )
}

plot_a <- build_compound(IPSUM_VP_BG, "grey25", theme_report)
save_plot(plot_a, "16a_winner_religion_action_donuts",
          width = 11, height = 11)

plot_b <- build_compound(IPSUM_VP_DARK_BG, IPSUM_VP_DARK_FG, theme_report_dark)
save_plot_dark(plot_b, "16b_winner_religion_action_donuts",
               width = 11, height = 11)
