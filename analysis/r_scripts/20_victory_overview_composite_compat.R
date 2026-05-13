# 20_compat: Victory Overview composite for the compat (older) dataset.
# Same 4-row layout as 20_victory_overview_composite.R but reads data from
# the compat dataset (defaults to the WSL log-processor output) and writes
# outputs under output/r_plots/compat/dark/composites/.
#
# Must be run AFTER 02_winrate_by_civ_compat.R and
# 04_pseudo_dom_winrate_by_civ_compat.R have produced their _nocap PNGs.
source("r_scripts/common_compat.R")
suppressPackageStartupMessages(library(magick))

DARK_DIR  <- OUTPUT_DIR_DARK
COMP_DIR  <- file.path(DARK_DIR, "composites")
dir.create(COMP_DIR, recursive = TRUE, showWarnings = FALSE)

BG  <- IPSUM_VP_DARK_BG
FG  <- IPSUM_VP_DARK_FG
LUT <- vtc_lut_b

aug_df <- build_augmented_game_result()

# ---------------------------------------------------------------------------
# Donut geometry helpers (copied from 20).
# ---------------------------------------------------------------------------
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

build_donut_panel <- function(df, type_col, levels, title) {
    counts <- df %>%
        count(!!sym(type_col), .drop = FALSE, name = "games") %>%
        filter(games > 0) %>%
        mutate(
            !!type_col := factor(.data[[type_col]], levels = levels),
            share = games / sum(games),
            label = sprintf("%s\n%d  (%s)",
                            .data[[type_col]], games, percent(share, 1))
        )

    bounds <- counts %>%
        arrange(.data[[type_col]]) %>%
        mutate(
            cum_end   = cumsum(share),
            cum_start = lag(cum_end, default = 0),
            theta0    = pi/2 - 2*pi * cum_start,
            theta1    = pi/2 - 2*pi * cum_end,
            theta_mid = (theta0 + theta1) / 2
        )

    polys <- bounds %>%
        rowwise() %>%
        do({
            sl <- make_slice(.$theta0, .$theta1, r_in, r_out)
            sl[[type_col]] <- .[[type_col]]
            sl
        }) %>%
        ungroup() %>%
        mutate(!!type_col := factor(.data[[type_col]], levels = levels))

    leaders <- bounds %>%
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

    ggplot() +
        geom_polygon(data = polys,
                     aes(x = x, y = y, group = .data[[type_col]],
                         fill = .data[[type_col]]),
                     color = BG, linewidth = 0.6) +
        geom_segment(data = leaders,
                     aes(x = x_stub_start, y = y_stub_start,
                         xend = x_elbow,    yend = y_elbow,
                         color = .data[[type_col]]),
                     linewidth = 0.5) +
        geom_segment(data = leaders,
                     aes(x = x_elbow, y = y_elbow,
                         xend = x_lbl,  yend = y_lbl,
                         color = .data[[type_col]]),
                     linewidth = 0.5) +
        geom_text(data = leaders,
                  aes(x = x_lbl, y = y_lbl, label = label, hjust = hjust),
                  size = 3.8, fontface = "bold", lineheight = 0.95,
                  vjust = 0.5, color = FG, show.legend = FALSE) +
        coord_fixed(xlim = c(-1.95, 1.95), ylim = c(-1.25, 1.25),
                    clip = "off") +
        scale_fill_manual(values = LUT, drop = FALSE, guide = "none") +
        scale_color_manual(values = LUT, drop = FALSE, guide = "none") +
        labs(title = title) +
        theme_void(base_family = "") +
        theme(
            plot.background = element_rect(fill = BG, color = BG),
            plot.title  = element_text(face = "bold", size = 16, hjust = 0.5,
                                       color = FG),
            plot.margin = margin(10, 30, 10, 30),
            legend.position = "none"
        )
}

# ---------------------------------------------------------------------------
# Violin + beeswarm panels.
# ---------------------------------------------------------------------------
y_min <- min(c(game_result_df$turn, aug_df$turn_aug), na.rm = TRUE)
y_max <- max(c(game_result_df$turn, aug_df$turn_aug), na.rm = TRUE)
y_pad <- 0.04 * (y_max - y_min)
y_lim <- c(y_min - y_pad, y_max + y_pad)

build_violin_panel <- function(df, x_col, y_col, title) {
    ggplot(df,
           aes(x = .data[[x_col]], y = .data[[y_col]],
               fill = .data[[x_col]])) +
        geom_violin(trim = FALSE, alpha = 0.85, color = BG,
                    linewidth = 0.45, scale = "width") +
        geom_quasirandom(aes(fill = .data[[x_col]]),
                         shape = 21, color = "black", stroke = 0.6,
                         width = 0.28, size = 2.4, alpha = 0.95,
                         show.legend = FALSE) +
        scale_fill_manual(values = LUT, drop = FALSE, guide = "none") +
        scale_color_manual(values = LUT, drop = FALSE) +
        scale_y_continuous(labels = comma, limits = y_lim,
                           oob = scales::squish) +
        labs(title = title, x = NULL, y = "Game-ending turn") +
        theme_report_dark(base_size = 12) +
        theme(legend.position  = "none",
              axis.text.x      = element_text(angle = 20, hjust = 1),
              plot.background  = element_rect(fill = BG, color = NA),
              panel.background = element_rect(fill = BG, color = NA))
}

donut1  <- build_donut_panel(game_result_df, "victory_type",
                             VICTORY_LEVELS, "Victory Type Share")
donut2  <- build_donut_panel(aug_df, "victory_type_aug",
                             VICTORY_LEVELS_AUG,
                             "Authority Victory Type Share")
violin1 <- build_violin_panel(game_result_df, "victory_type", "turn",
                              "Victory Time Spread")
violin2 <- build_violin_panel(aug_df, "victory_type_aug", "turn_aug",
                              "Authority Victory Time Spread")

caption_text <- default_caption()

top_block <- (donut1 | donut2) / (violin1 | violin2) +
    plot_layout(heights = c(1, 1)) &
    theme(plot.background  = element_rect(fill = BG, color = NA),
          panel.background = element_rect(fill = BG, color = NA))

TOP_PATH <- file.path(COMP_DIR, "_victory_overview_top.png")
ggsave(TOP_PATH, top_block, width = 14, height = 12, dpi = 150, bg = BG)
cat("saved:", TOP_PATH, "\n")

# ---------------------------------------------------------------------------
# Stack: top block | 02b_nocap | 04b_nocap from compat output dir.
# ---------------------------------------------------------------------------
read_img <- function(path) {
    if (!file.exists(path)) stop("Missing image: ", path)
    image_read(path)
}

p02  <- read_img(file.path(DARK_DIR,
                            "02b_winrate_by_civ_stacked_bars_nocap.png"))
p04  <- read_img(file.path(DARK_DIR,
                            "04b_pseudo_dom_winrate_by_civ_nocap.png"))
ptop <- read_img(TOP_PATH)

imgs     <- c(ptop, p02, p04)
target_w <- max(image_info(imgs)$width)
scaled   <- lapply(seq_along(imgs), function(i) {
    image_scale(imgs[i], paste0(target_w, "x"))
})
composite <- image_append(do.call(c, scaled), stack = TRUE)

caption_h <- 100L
info_c    <- image_info(composite)
canvas    <- image_blank(width = info_c$width,
                         height = info_c$height + caption_h,
                         color = BG)
composite <- image_composite(canvas, composite, offset = "+0+0")
composite <- image_annotate(
    composite, caption_text,
    gravity  = "southeast",
    location = "+24+10",
    size     = 18,
    color    = "grey60",
    style    = "italic"
)

OUT_PATH <- file.path(COMP_DIR, "victory_overview.png")
image_write(composite, OUT_PATH, format = "png")
cat("saved:", OUT_PATH, "\n")

unlink(TOP_PATH)
