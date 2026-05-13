# 22: Civ winrate / rank comparison between VP 4.15.2 4UC and VP 5.2.3 4UC.
#
# Tabular visualization. Rows = civs (one per civ), ordered by 4.15.2 winrate
# (highest at top). Columns:
#   Civ | 4.15.2 Rank | 5.2.3 Rank | Rank Change || 4.15.2 WR | 5.2.3 WR | WR Change
# Only the two "Change" columns get a heatmap fill.
source("r_scripts/common.R")

OLD_CSV <- file.path("..", "misc", "4_15_2_4uc_civ_stats.csv")

old_df <- suppressMessages(read_csv(OLD_CSV)) %>%
    select(civ = Civ, winrate_old = Winrate)

new_df <- load_spark_csv("power_ranking") %>%
    select(civ, winrate_new = winrate) %>%
    mutate(winrate_new = as.numeric(winrate_new))

# Standardize civ names so the join works. Both CSVs already use "The X"
# form for civs that need it; just trim whitespace just in case.
old_df <- old_df %>% mutate(civ = stringr::str_trim(civ))
new_df <- new_df %>% mutate(civ = stringr::str_trim(civ))

cmp <- full_join(old_df, new_df, by = "civ") %>%
    mutate(
        rank_old = rank(-winrate_old, ties.method = "first"),
        rank_new = rank(-winrate_new, ties.method = "first"),
        # Rank Change going old -> new. Lower rank number = better, so we
        # display rank_old - rank_new so improvement (moved up the table)
        # reads as a *positive* delta and a decline as a *negative* one --
        # matching the winrate-change column's sign convention.
        rank_delta = rank_old - rank_new,
        # Winrate change in percentage points.
        wr_delta_pp = (winrate_new - winrate_old) * 100
    ) %>%
    arrange(rank_old)

stopifnot(nrow(cmp) == 43L)

# ---- Cell text + fill helpers (vectorized) -----------------------------------

UP <- "\u25B2"   # up triangle = improvement
DN <- "\u25BC"   # down triangle = decline

rank_delta_label <- function(delta) {
    mag <- abs(delta)
    # Positive delta = improvement (moved up the table) -> UP arrow.
    sym <- ifelse(delta > 0, UP, DN)
    suffix <- ifelse(mag == 0, "",
              ifelse(mag >= 10, paste0(" ", sym, sym),
                                paste0(" ", sym)))
    out <- ifelse(is.na(delta), "",
                  ifelse(mag == 0, "-",
                         paste0(sprintf("%+d", delta), suffix)))
    out
}

# Winrate change label. Magnitude is in percentage points.
wr_delta_label <- function(delta_pp) {
    mag <- abs(delta_pp)
    sym <- ifelse(delta_pp > 0, UP, DN)
    suffix <- ifelse(mag >= 5, paste0(" ", sym, sym),
             ifelse(mag > 1,  paste0(" ", sym), ""))
    out <- ifelse(is.na(delta_pp), "",
                  paste0(sprintf("%+.1f", delta_pp), "%", suffix))
    out
}

cmp <- cmp %>%
    mutate(
        rank_delta_txt = rank_delta_label(rank_delta),
        wr_delta_txt   = wr_delta_label(wr_delta_pp)
    )

# ---- Long-format cell tibble for ggplot --------------------------------------

# Column slots (x positions) and per-column text. Heatmap fills apply only
# to the two delta columns; other cells get NA fill so they read as panel bg.
COLS <- c(
    "Civ",
    "4.15.2 Rank",
    "5.2.3 Rank",
    "Rank Change",
    "4.15.2 Winrate",
    "5.2.3 Winrate",
    "Winrate Change"
)

cell_df <- cmp %>%
    transmute(
        civ,
        rank_old,
        text_civ        = civ,
        text_rank_old   = as.character(rank_old),
        text_rank_new   = as.character(rank_new),
        text_rank_delta = rank_delta_txt,
        text_wr_old     = sprintf("%.1f%%", winrate_old * 100),
        text_wr_new     = sprintf("%.1f%%", winrate_new * 100),
        text_wr_delta   = wr_delta_txt,
        fill_rank_delta = rank_delta,
        fill_wr_delta   = wr_delta_pp
    )

n_civs <- nrow(cell_df)   # 43
# Top = best 4.15.2 rank. We assign y = n_civs - rank_old + 1 so that
# rank 1 sits at the top of the plot.
cell_df <- cell_df %>% mutate(y = n_civs - rank_old + 1)

long_df <- bind_rows(
    cell_df %>% transmute(y, col = 1, label = text_civ,        fill = NA_real_,
                          hjust = 0, is_civ = TRUE, kind = "civ"),
    cell_df %>% transmute(y, col = 2, label = text_rank_old,   fill = NA_real_,
                          hjust = 0.5, is_civ = FALSE, kind = "num"),
    cell_df %>% transmute(y, col = 3, label = text_rank_new,   fill = NA_real_,
                          hjust = 0.5, is_civ = FALSE, kind = "num"),
    cell_df %>% transmute(y, col = 4, label = text_rank_delta, fill = fill_rank_delta,
                          hjust = 0.5, is_civ = FALSE, kind = "rank_delta"),
    cell_df %>% transmute(y, col = 5, label = text_wr_old,     fill = NA_real_,
                          hjust = 0.5, is_civ = FALSE, kind = "num"),
    cell_df %>% transmute(y, col = 6, label = text_wr_new,     fill = NA_real_,
                          hjust = 0.5, is_civ = FALSE, kind = "num"),
    cell_df %>% transmute(y, col = 7, label = text_wr_delta,   fill = fill_wr_delta,
                          hjust = 0.5, is_civ = FALSE, kind = "wr_delta")
)

# Symmetric color scaling around 0 so red = decline, green = improvement.
# Rank: improvement = negative delta -> green; decline = positive -> red.
# Winrate: improvement = positive delta -> green; decline = negative -> red.
# We flip the rank fill so the gradient maps the same intuition to both
# columns (green = good, red = bad) via a single shared scale.
long_df <- long_df %>%
    mutate(fill_signed = case_when(
        kind == "rank_delta" ~ -fill,                     # invert sign
        kind == "wr_delta"   ~ fill,                       # already pp
        TRUE                 ~ NA_real_
    ))

rank_lim <- max(abs(cmp$rank_delta), na.rm = TRUE)
wr_lim   <- max(abs(cmp$wr_delta_pp), na.rm = TRUE)
# Normalize each delta to [-1, 1] relative to its own column's max magnitude,
# so both columns can share one fill scale. Both deltas now follow the
# convention "positive = good" so no sign flip is needed.
long_df <- long_df %>%
    mutate(fill_norm = case_when(
        kind == "rank_delta" ~ fill / max(rank_lim, 1),
        kind == "wr_delta"   ~ fill / max(wr_lim, 1e-9),
        TRUE                 ~ NA_real_
    ))

long_df <- long_df %>%
    mutate(text_color = NA_character_)

# Vertical separator positions: between cols 1|2 (thin), 4|5 (thick), and 4|5
# user-spec also calls for a thick divider after col 1 (Civ) before the rank
# block. So thick dividers go at x = 1.5 and x = 4.5.
thick_x <- c(1.5, 4.5)

build_table <- function(theme_fn, bg, tile_outline, text_color,
                        sep_color, fg) {
    # Diverging palette: red (decline) -> bg (neutral) -> green (improvement).
    rdylgn_colors <- colorRampPalette(c("firebrick", bg, "forestgreen"))(11)
    
    # Body extends x in [0.5, 7.5] and y in [0.5, n_civs + 0.5]; the header
    # strip sits at y = n_civs + 1 (covering [n_civs + 0.5, n_civs + 1.5]).
    body_x_min <- 0.5
    body_x_max <- length(COLS) + 0.5
    body_y_min <- 0.5
    body_y_max <- n_civs + 0.5
    header_y_max <- n_civs + 1.5
    # Thick verticals stop flush with the bottom of the body.
    thick_y_min <- body_y_min
    # Thin vertical column gridlines (skip the positions used by thick lines).
    thin_x <- setdiff(seq_len(length(COLS) - 1) + 0.5, thick_x)

    p <- ggplot(long_df, aes(x = col, y = y)) +
        # Heatmap fill only for delta columns (others get bg via na.value).
        # No per-tile outline -- we draw explicit gridlines below for crisper
        # control over which borders extend into the header / past the body.
        geom_tile(aes(fill = fill_norm),
                  width = 1, height = 1) +
        scale_fill_gradientn(colours = rdylgn_colors,
                             values  = scales::rescale(seq(-1, 1, length.out = 11)),
                             limits  = c(-1, 1),
                             na.value = bg, guide = "none") +
        # Cell text. Civ column is left-aligned, others centered.
        geom_text(data = long_df %>% filter(is_civ),
                  aes(label = label), hjust = 0, nudge_x = -0.45,
                  size = 3.4, color = text_color, fontface = "bold") +
        geom_text(data = long_df %>% filter(!is_civ, is.na(text_color)),
                  aes(label = label), size = 3.4, color = text_color) +
        geom_text(data = long_df %>% filter(!is_civ, !is.na(text_color)),
                  aes(label = label, color = text_color), size = 3.4,
                  show.legend = FALSE) +
        scale_color_identity() +
        # Thin horizontal cell separators (between rows) within the body.
        annotate("segment",
                 x = body_x_min, xend = body_x_max,
                 y = seq_len(n_civs - 1) + 0.5,
                 yend = seq_len(n_civs - 1) + 0.5,
                 color = tile_outline, linewidth = 0.3) +
        # Thin vertical column separators -- extend up into the header row
        # but stop flush with the bottom of the body.
        annotate("segment",
                 x = thin_x, xend = thin_x,
                 y = body_y_min, yend = header_y_max,
                 color = tile_outline, linewidth = 0.3) +
        # Outer body border (left/right/top/bottom) lined up with the
        # thick horizontal divider span.
        annotate("segment",
                 x = c(body_x_min, body_x_max),
                 xend = c(body_x_min, body_x_max),
                 y = body_y_min, yend = header_y_max,
                 color = tile_outline, linewidth = 0.3) +
        annotate("segment",
                 x = body_x_min, xend = body_x_max,
                 y = c(body_y_min, header_y_max),
                 yend = c(body_y_min, header_y_max),
                 color = tile_outline, linewidth = 0.3) +
        # Thick vertical category dividers -- extend past the bottom of the
        # table further than the thin verticals, and up into the header.
        annotate("segment",
                 x = thick_x, xend = thick_x,
                 y = thick_y_min, yend = header_y_max,
                 color = sep_color, linewidth = 1.1) +
        # Thick horizontal divider between header strip and body, spanning
        # exactly the table width.
        annotate("segment",
                 x = body_x_min, xend = body_x_max,
                 y = body_y_max, yend = body_y_max,
                 color = sep_color, linewidth = 1.1) +
        # Header strip text. Civ header anchors at left edge of its cell
        # to match the left-aligned Civ-cell text.
        annotate("text",
                 x = c(0.55, 2, 3, 4, 5, 6, 7),
                 y = n_civs + 1,
                 label = COLS,
                 fontface = "bold", size = 3.6, color = fg,
                 hjust = c(0, rep(0.5, 6)),
                 vjust = 0.5) +
        scale_x_continuous(breaks = NULL,
                           limits = c(0.3, length(COLS) + 0.7),
                           expand = c(0, 0)) +
        scale_y_continuous(breaks = NULL,
                           limits = c(body_y_min - 0.2, header_y_max + 0.3),
                           expand = c(0, 0)) +
        labs(title = "Civ Winrate & Rank: VP 4.15.2 4UC \u2192 VP 5.2.3 4UC",
             caption = NULL,
             x = NULL, y = NULL) +
        theme_fn(base_size = 12) +
        theme(panel.grid       = element_blank(),
              panel.background = element_rect(fill = bg, color = NA),
              axis.text        = element_blank(),
              axis.ticks       = element_blank())
    p
}

# Civ-header left nudge: handled inline above via custom x positions.

p_light <- build_table(theme_report,
                       bg = IPSUM_VP_BG,
                       tile_outline = "grey80",
                       text_color = "grey15",
                       sep_color = "grey25",
                       fg = "grey15")

p_dark <- build_table(theme_report_dark,
                      bg = IPSUM_VP_DARK_BG,
                      tile_outline = "grey30",
                      text_color = IPSUM_VP_DARK_FG,
                      sep_color = "grey55",
                      fg = IPSUM_VP_DARK_FG)

# Approx sizing: ~0.32" per row + header/title space.
plot_h <- max(10, 0.32 * n_civs + 3)
plot_w <- 11

save_plot(p_light, "22a_winrate_version_compare",
          width = plot_w, height = plot_h)
save_plot_dark(p_dark, "22b_winrate_version_compare",
               width = plot_w, height = plot_h)
