# 03: Pseudo-domination version of the victory mix.
# Same donut + violin layout as 01, but a game's effective winner becomes
# the FIRST civ to reach the >=66% tiles+cities authority threshold
# (`pseudo_victory == 1`), with `victory_type_aug = "Authority"`
# and `turn_aug` = that early threshold turn. Domination wins are also
# reclassified when an authority-threshold crossing predates the dom
# victory (even by the same civ), so the Domination count here is
# strictly less than in 01/02.
# Because pseudo-dom wins always fire on or before the recorded
# game-ending turn, the violin distribution skews EARLIER than 01's.
# Produces:
#   03a_pseudo_dom_victory_mix.png   light theme + vtc_lut_a
#   03b_pseudo_dom_victory_mix.png   dark theme  + vtc_lut_b
source("r_scripts/common.R")

aug_df <- build_augmented_game_result()

victory_counts <- aug_df %>%
    count(victory_type_aug, .drop = FALSE, name = "games") %>%
    filter(games > 0) %>%
    mutate(
        victory_type_aug = factor(victory_type_aug, levels = VICTORY_LEVELS_AUG),
        share = games / sum(games),
        label = sprintf("%s\n%d  (%s)", victory_type_aug, games, percent(share, 1))
    )

# --- Donut geometry ---------------------------------------------------------
make_slice <- function(theta0, theta1, r_in, r_out, n = 60) {
    th_out <- seq(theta0, theta1, length.out = n)
    th_in  <- rev(th_out)
    data.frame(
        x = c(r_out * cos(th_out), r_in * cos(th_in)),
        y = c(r_out * sin(th_out), r_in * sin(th_in))
    )
}

r_in    <- 0.60
r_out   <- 1.00
r_elbow <- 1.10
r_lbl   <- 1.30

slice_bounds <- victory_counts %>%
    arrange(victory_type_aug) %>%
    mutate(
        cum_end   = cumsum(share),
        cum_start = lag(cum_end, default = 0),
        theta0    = pi/2 - 2*pi * cum_start,
        theta1    = pi/2 - 2*pi * cum_end,
        theta_mid = (theta0 + theta1) / 2
    )

slice_polys <- slice_bounds %>%
    rowwise() %>%
    do({
        sl <- make_slice(.$theta0, .$theta1, r_in, r_out)
        sl$victory_type_aug <- .$victory_type_aug
        sl
    }) %>%
    ungroup() %>%
    mutate(victory_type_aug = factor(victory_type_aug, levels = VICTORY_LEVELS_AUG))

leader_df <- slice_bounds %>%
    mutate(
        x_stub_start = r_out  * cos(theta_mid),
        y_stub_start = r_out  * sin(theta_mid),
        x_elbow      = r_elbow * cos(theta_mid),
        y_elbow      = r_elbow * sin(theta_mid),
        side  = ifelse(cos(theta_mid) >= 0, "right", "left"),
        x_lbl = ifelse(side == "right",  r_lbl, -r_lbl),
        y_lbl = y_elbow,
        hjust = ifelse(side == "right", 0, 1)
    )

build_donut <- function(lut, bg, label_color) {
    ggplot() +
        geom_polygon(data = slice_polys,
                     aes(x = x, y = y, group = victory_type_aug,
                         fill = victory_type_aug),
                     color = bg, linewidth = 0.6) +
        geom_segment(data = leader_df,
                     aes(x = x_stub_start, y = y_stub_start,
                         xend = x_elbow,    yend = y_elbow,
                         color = victory_type_aug),
                     linewidth = 0.5) +
        geom_segment(data = leader_df,
                     aes(x = x_elbow, y = y_elbow,
                         xend = x_lbl,  yend = y_lbl,
                         color = victory_type_aug),
                     linewidth = 0.5) +
        geom_text(data = leader_df,
                  aes(x = x_lbl, y = y_lbl, label = label, hjust = hjust),
                  size = 3.8, fontface = "bold", lineheight = 0.95,
                  vjust = 0.5, color = label_color, show.legend = FALSE) +
        coord_fixed(xlim = c(-1.95, 1.95), ylim = c(-1.25, 1.25), clip = "off") +
        scale_fill_manual(values = lut, drop = FALSE, guide = "none") +
        scale_color_manual(values = lut, drop = FALSE, guide = "none") +
        labs(title = "Victory Type Share") +
        theme_void(base_family = "") +
        theme(
            plot.background = element_rect(fill = bg, color = bg),
            plot.title  = element_text(face = "bold", size = 16, hjust = 0.5,
                                       color = label_color),
            plot.margin = margin(10, 30, 10, 30),
            legend.position = "none"
        )
}

build_violin_bees <- function(lut, bg, theme_fn, bee_outline) {
    ggplot(aug_df,
           aes(x = victory_type_aug, y = turn_aug, fill = victory_type_aug)) +
        geom_violin(trim = FALSE, alpha = 0.85, color = bg,
                    linewidth = 0.45, scale = "width") +
        geom_quasirandom(aes(fill = victory_type_aug),
                         shape = 21, color = bee_outline, stroke = 0.6,
                         width = 0.28, size = 2.4, alpha = 0.95,
                         show.legend = FALSE) +
        scale_fill_manual(values = lut, drop = FALSE, guide = "none") +
        scale_color_manual(values = lut, drop = FALSE) +
        scale_y_continuous(labels = comma) +
        labs(title = "Victory Time Spread",
             x = NULL, y = "Game-ending turn") +
        theme_fn(base_size = 12) +
        theme(legend.position = "none",
              axis.text.x = element_text(angle = 20, hjust = 1))
}

caption_text <- default_caption()

compose <- function(left, right, theme_fn, caption_color) {
    annotation_theme <- theme_fn(base_size = 13) +
        theme(plot.caption = element_text(color = caption_color, size = 11,
                                          hjust = 1, face = "italic"))
    (left | right) +
        plot_layout(widths = c(1, 1)) +
        plot_annotation(caption = caption_text, theme = annotation_theme)
}

plot_a <- compose(
    build_donut(vtc_lut_a, IPSUM_VP_BG, "grey25"),
    build_violin_bees(vtc_lut_a, IPSUM_VP_BG, theme_report, "black"),
    theme_report, "grey25"
)
save_plot(plot_a, "03a_pseudo_dom_victory_mix", width = 14, height = 7)

plot_b <- compose(
    build_donut(vtc_lut_b, IPSUM_VP_DARK_BG, IPSUM_VP_DARK_FG),
    build_violin_bees(vtc_lut_b, IPSUM_VP_DARK_BG, theme_report_dark, "black"),
    theme_report_dark, "grey60"
)
save_plot_dark(plot_b, "03b_pseudo_dom_victory_mix", width = 14, height = 7)
save_plot_dark_nocap(plot_b, "03b_pseudo_dom_victory_mix_nocap",
                     width = 14, height = 7)
