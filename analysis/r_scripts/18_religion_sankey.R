# 18: Religious-action Sankey across 5 stages.
#
#   Col 1: Secular (took none of the 4 actions)
#   Col 2: Pantheon (any civ that founded a pantheon)
#   Col 3: Founded a Religion (any civ that founded a religion)
#   Col 4: Enhanced a Religion | Reformed a Religion (two nodes, non-exclusive)
#   Col 5: Enhanced + Reformed a Religion (civs that did both)
#
# Each node is a stacked red/green rectangle: green = wins, red = losses,
# labelled with N wins / N losses / winrate.  Connections are flat grey
# bezier ribbons proportional to the number of civs in the intersection.
#
# Outputs:
#   18a_religion_sankey.png   light theme
#   18b_religion_sankey.png   dark theme

source("r_scripts/common.R")

# --- Reuse 17's bad-game filter (truncation + roster mismatch). ------------
religion_choices_df <- load_spark_csv("religion_choices")
religion_choices_df <- synth_clone_per_game(religion_choices_df, "religion_choices_df")
civ_choices_df_raw  <- load_spark_csv("civ_choices")
civ_choices_df_raw  <- synth_clone_per_game(civ_choices_df_raw, "civ_choices_df_raw")

all_real_ids <- unique(game_result_df$game_id)

pantheon_counts <- religion_choices_df %>%
    filter(type == "pantheon") %>%
    count(game_id, name = "n_pantheon")
pantheon_counts <- tibble::tibble(game_id = all_real_ids) %>%
    left_join(pantheon_counts, by = "game_id") %>%
    mutate(n_pantheon = ifelse(is.na(n_pantheon), 0L, n_pantheon))

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
    mutate(rc_n = length(rc_civs %||% character(0)),
           roster_mismatch = rc_n > 0 &&
                             length(setdiff(rc_civs, cc_civs)) > 0) %>%
    ungroup() %>%
    select(game_id, roster_mismatch)

bad_ids <- pantheon_counts %>%
    left_join(roster_check, by = "game_id") %>%
    mutate(roster_mismatch = ifelse(is.na(roster_mismatch), FALSE, roster_mismatch),
           bad = (n_pantheon != 8) | roster_mismatch) %>%
    filter(bad) %>%
    pull(game_id)

cat(sprintf("Filtering out %d games with bad religion logs.\n", length(bad_ids)))

civ_choices_df <- civ_choices_df_raw %>% filter(!game_id %in% bad_ids)
game_result_df <- game_result_df       %>% filter(!game_id %in% bad_ids)

# --- Per-civ predicates + win flag. -----------------------------------------
did <- function(col) !is.na(col) & nzchar(as.character(col))

# First-action ordering from religion_choices: for civs that did both enhance
# and reform, was enhance the earlier action?  Uses the `turn` column.
first_action <- religion_choices_df %>%
    filter(type %in% c("religion_enhanced", "religion_reformed"),
           !game_id %in% bad_ids) %>%
    group_by(game_id, civ) %>%
    summarise(
        enh_turn = suppressWarnings(min(turn[type == "religion_enhanced"])),
        ref_turn = suppressWarnings(min(turn[type == "religion_reformed"])),
        .groups = "drop"
    ) %>%
    mutate(
        enh_turn  = ifelse(is.finite(enh_turn), enh_turn, NA_real_),
        ref_turn  = ifelse(is.finite(ref_turn), ref_turn, NA_real_),
        enh_first = !is.na(enh_turn) &
                    (is.na(ref_turn) | enh_turn <= ref_turn)
    ) %>%
    select(game_id, civ, enh_first)

civs <- civ_choices_df %>%
    left_join(
        game_result_df %>% select(game_id, victory_civ),
        by = "game_id"
    ) %>%
    left_join(first_action, by = c("game_id", "civ")) %>%
    mutate(
        won       = !is.na(victory_civ) & civ == victory_civ,
        has_pan   = did(pantheon_founded),
        has_fnd   = did(religion_founded),
        has_enh   = did(religion_enhanced),
        has_ref   = did(religion_reformed),
        enh_first = ifelse(is.na(enh_first), FALSE, enh_first)
    ) %>%
    select(game_id, civ, won, has_pan, has_fnd, has_enh, has_ref, enh_first)

# Helper: counts (wins/losses/total) over a logical vector picking civs.
node_stats <- function(mask) {
    sub <- civs[mask, , drop = FALSE]
    list(total  = nrow(sub),
         wins   = sum(sub$won),
         losses = sum(!sub$won))
}

with(civs, {
    pan          <<- has_pan
    fnd          <<- has_fnd
    no_fnd       <<- has_pan & !has_fnd
    # Mutually exclusive col-3 masks based on which action came FIRST.
    # Civs that did both go to whichever they did first; civs that did only
    # one go to that one.
    enh          <<- has_enh & (!has_ref |  enh_first)
    ref          <<- has_ref & (!has_enh | !enh_first)
    neither      <<- has_fnd & !has_enh & !has_ref
    enh_only     <<- has_enh & !has_ref
    ref_only     <<- has_ref & !has_enh
    enh_ref      <<- has_enh & has_ref
})

# --- Node table: column index, label, counts. -------------------------------
# Column layout:
#   1: Pantheon
#   2: Founded a Religion | Did not Found
#   3: Enhanced | Reformed | Neither
#   4: Did not Reform | Enhanced + Reformed | Did not Enhance
nodes <- tibble::tribble(
    ~id,             ~col, ~label,                           ~mask,
    "pantheon",      1L,   "Founded a\nPantheon",            pan,
    "founded",       2L,   "Founded a\nReligion",            fnd,
    "no_found",      2L,   "Did not Found\na Religion",      no_fnd,
    "enhanced",      3L,   "Enhanced a\nReligion",           enh,
    "reformed",      3L,   "Reformed a\nReligion",           ref,
    "neither",       3L,   "Neither",                        neither,
    "did_not_ref",   4L,   "Did not\nReform",                enh_only,
    "enh_ref",       4L,   "Enhanced +\nReformed",           enh_ref,
    "did_not_enh",   4L,   "Did not\nEnhance",               ref_only
)
node_counts <- lapply(nodes$mask, node_stats)
nodes$total  <- vapply(node_counts, function(x) x$total,  integer(1))
nodes$wins   <- vapply(node_counts, function(x) x$wins,   integer(1))
nodes$losses <- vapply(node_counts, function(x) x$losses, integer(1))
nodes$winrate <- ifelse(nodes$total > 0, nodes$wins / nodes$total, 0)

# Within-column stacking order (top -> bottom).
node_order <- c("pantheon",
                "founded", "no_found",
                "enhanced", "reformed", "neither",
                "did_not_ref", "enh_ref", "did_not_enh")
nodes <- nodes[match(node_order, nodes$id), ]

# --- Links: source id, target id, count, wins. -----------------------------
link_specs <- list(
    list("pantheon",   "founded",      civs$has_pan & civs$has_fnd),
    list("pantheon",   "no_found",     civs$has_pan & !civs$has_fnd),
    list("founded",    "enhanced",     civs$has_fnd & enh),
    list("founded",    "reformed",     civs$has_fnd & ref),
    list("founded",    "neither",      civs$has_fnd & !civs$has_enh & !civs$has_ref),
    list("no_found",   "enhanced",     civs$has_pan & !civs$has_fnd & enh),
    list("no_found",   "reformed",     civs$has_pan & !civs$has_fnd & ref),
    list("enhanced",   "did_not_ref",  enh & !civs$has_ref),
    list("enhanced",   "enh_ref",      enh &  civs$has_ref),
    list("reformed",   "enh_ref",      ref &  civs$has_enh),
    list("reformed",   "did_not_enh",  ref & !civs$has_enh)
)
links <- tibble::tibble(
    src   = vapply(link_specs, function(x) x[[1]], character(1)),
    tgt   = vapply(link_specs, function(x) x[[2]], character(1)),
    count = vapply(link_specs, function(x) sum(x[[3]]), integer(1)),
    wins  = vapply(link_specs, function(x) sum(x[[3]] & civs$won), integer(1))
)
links$losses <- links$count - links$wins

# Compute per-node ribbon scale factors so ribbon slices always fit inside
# node bounds.  When a node's incoming or outgoing flow exceeds its actual
# count (only happens at enh_ref due to the double-counted overlap), we
# compress the slice heights proportionally.
out_sum <- links %>% group_by(src) %>%
    summarise(s = sum(count), .groups = "drop")
in_sum  <- links %>% group_by(tgt) %>%
    summarise(s = sum(count), .groups = "drop")
nodes$out_total <- out_sum$s[match(nodes$id, out_sum$src)]
nodes$in_total  <- in_sum$s[match(nodes$id,  in_sum$tgt)]
nodes$out_total[is.na(nodes$out_total)] <- 0
nodes$in_total[is.na(nodes$in_total)]   <- 0
scale_out <- setNames(
    pmin(1, nodes$total / pmax(1, nodes$out_total)), nodes$id)
scale_in  <- setNames(
    pmin(1, nodes$total / pmax(1, nodes$in_total)),  nodes$id)

# --- Layout: each node occupies y-range [y0, y1].  Columns share scale. ----
NODE_W      <- 0.35
COL_X       <- c(1, 2, 3, 4)
INTRA_GAP   <- 0.30   # fraction of max-column-total used as gap between
                      # stacked nodes within the same column.

# Node heights are proportional to actual counts (total civs per node).
col_totals <- nodes %>% group_by(col) %>%
    summarise(sum_total = sum(total), n_nodes = dplyr::n(), .groups = "drop")
max_col_total <- max(col_totals$sum_total)
gap_size      <- INTRA_GAP * max_col_total

assign_y <- function(df) {
    n <- nrow(df)
    sum_h <- sum(df$total) + (n - 1) * gap_size
    y_top <- sum_h / 2
    out <- df
    out$y1 <- numeric(n)
    out$y0 <- numeric(n)
    cur_top <- y_top
    for (i in seq_len(n)) {
        out$y1[i] <- cur_top
        out$y0[i] <- cur_top - df$total[i]
        cur_top   <- out$y0[i] - gap_size
    }
    out
}
nodes <- nodes %>% group_by(col) %>% group_modify(~ assign_y(.x)) %>% ungroup()
nodes$x  <- COL_X[nodes$col]
nodes$xl <- nodes$x - NODE_W / 2
nodes$xr <- nodes$x + NODE_W / 2

# Ribbon allocation: slice heights scaled so ribbons fit within node bounds.
# Outgoing (and incoming) slice stacks are vertically centered against the
# node, so when total flow on one side is much smaller than the node height
# (e.g. tiny no_found -> enhanced/reformed exits) the ribbons emerge from the
# middle of the node rather than its top edge.
node_idx <- setNames(seq_len(nrow(nodes)), nodes$id)
node_mid <- setNames((nodes$y0 + nodes$y1) / 2, nodes$id)

# Sum of scaled slice heights per source / target, in link order.
out_scaled <- setNames(numeric(nrow(nodes)), nodes$id)
in_scaled  <- setNames(numeric(nrow(nodes)), nodes$id)
for (i in seq_len(nrow(links))) {
    s <- links$src[i]; t <- links$tgt[i]; c <- links$count[i]
    out_scaled[s] <- out_scaled[s] + c * scale_out[s]
    in_scaled[t]  <- in_scaled[t]  + c * scale_in[t]
}
src_cursor <- setNames(node_mid + out_scaled / 2, nodes$id)
tgt_cursor <- setNames(node_mid + in_scaled  / 2, nodes$id)

links$src_y_top <- NA_real_
links$src_y_bot <- NA_real_
links$tgt_y_top <- NA_real_
links$tgt_y_bot <- NA_real_
links$src_x     <- NA_real_
links$tgt_x     <- NA_real_
for (i in seq_len(nrow(links))) {
    s  <- links$src[i]; t <- links$tgt[i]; c <- links$count[i]
    sc <- c * scale_out[s]   # scaled outgoing slice height
    tc <- c * scale_in[t]    # scaled incoming slice height
    links$src_y_top[i] <- src_cursor[s]
    links$src_y_bot[i] <- src_cursor[s] - sc
    src_cursor[s]      <- src_cursor[s] - sc
    links$tgt_y_top[i] <- tgt_cursor[t]
    links$tgt_y_bot[i] <- tgt_cursor[t] - tc
    tgt_cursor[t]      <- tgt_cursor[t] - tc
    links$src_x[i]     <- nodes$xr[node_idx[s]]
    links$tgt_x[i]     <- nodes$xl[node_idx[t]]
}

# Build smooth-step ribbons (cubic).  Each ribbon is a polygon with
# `n_seg` top-edge points then `n_seg` bottom-edge points reversed.
smooth_step <- function(t) 3 * t^2 - 2 * t^3
build_ribbon_polys <- function(links, n_seg = 80) {
    out <- vector("list", nrow(links))
    for (i in seq_len(nrow(links))) {
        x_seq <- seq(links$src_x[i], links$tgt_x[i], length.out = n_seg)
        t     <- (x_seq - links$src_x[i]) / (links$tgt_x[i] - links$src_x[i])
        s     <- smooth_step(t)
        y_top <- links$src_y_top[i] + (links$tgt_y_top[i] - links$src_y_top[i]) * s
        y_bot <- links$src_y_bot[i] + (links$tgt_y_bot[i] - links$src_y_bot[i]) * s
        out[[i]] <- data.frame(
            link_id = i,
            x = c(x_seq, rev(x_seq)),
            y = c(y_top, rev(y_bot))
        )
    }
    bind_rows(out)
}
ribbons <- build_ribbon_polys(links)

# Variant: split each ribbon into a top (wins) sub-ribbon and a bottom
# (losses) sub-ribbon proportional to the per-link win count.
build_ribbon_polys_split <- function(links, n_seg = 80) {
    out <- vector("list", nrow(links) * 2)
    k <- 0
    for (i in seq_len(nrow(links))) {
        if (links$count[i] <= 0) next
        x_seq <- seq(links$src_x[i], links$tgt_x[i], length.out = n_seg)
        t     <- (x_seq - links$src_x[i]) / (links$tgt_x[i] - links$src_x[i])
        s     <- smooth_step(t)
        p     <- links$wins[i] / links$count[i]
        # src/tgt slice heights.
        sc <- links$src_y_top[i] - links$src_y_bot[i]
        tc <- links$tgt_y_top[i] - links$tgt_y_bot[i]
        # Win sub-ribbon: top of link slice down to win fraction.
        src_win_top <- links$src_y_top[i]
        src_win_bot <- links$src_y_top[i] - sc * p
        tgt_win_top <- links$tgt_y_top[i]
        tgt_win_bot <- links$tgt_y_top[i] - tc * p
        if (p > 0) {
            y_top <- src_win_top + (tgt_win_top - src_win_top) * s
            y_bot <- src_win_bot + (tgt_win_bot - src_win_bot) * s
            k <- k + 1
            out[[k]] <- data.frame(
                link_id = i, outcome = "win",
                x = c(x_seq, rev(x_seq)),
                y = c(y_top, rev(y_bot))
            )
        }
        # Lose sub-ribbon: from win bottom down to slice bottom.
        if (p < 1) {
            y_top <- src_win_bot + (tgt_win_bot - src_win_bot) * s
            y_bot_src <- links$src_y_bot[i]
            y_bot_tgt <- links$tgt_y_bot[i]
            y_bot <- y_bot_src + (y_bot_tgt - y_bot_src) * s
            k <- k + 1
            out[[k]] <- data.frame(
                link_id = i, outcome = "lose",
                x = c(x_seq, rev(x_seq)),
                y = c(y_top, rev(y_bot))
            )
        }
    }
    bind_rows(out[seq_len(k)])
}
ribbons_split <- build_ribbon_polys_split(links)

# Annotation for the no_found -> enhanced/reformed ribbons.  Placed at the
# bottom-center with a single leader arrow to the top-right corner of the
# "Did not Found a Religion" node (~10 px right and ~10 px down).
.span    <- max(nodes$y1) - min(nodes$y0)
.label_x <- mean(COL_X[2:3])               # between cols 2 and 3
.label_y <- min(nodes$y0) - 0.07 * .span   # below all nodes

ribbon_labels <- tibble::tibble(
    x    = .label_x,
    y    = .label_y,
    text = "Enhanced/Reformed a\nConquered Religion"
)
.nf <- nodes[nodes$id == "no_found", ]
if (nrow(.nf) > 0) {
    ribbon_leaders <- tibble::tibble(
        x    = .label_x,
        y    = .label_y + 0.025 * .span,
        xend = .nf$xr + 0.03,
        yend = .nf$y1 - 0.007 * .span
    )
} else {
    ribbon_leaders <- tibble::tibble(x = numeric(0), y = numeric(0),
                                     xend = numeric(0), yend = numeric(0))
}

# --- Build node geometry (stacked green/red rects). ------------------------
node_rects <- nodes %>%
    rowwise() %>%
    mutate(
        # Green (wins) on top, red (losses) below, heights = actual counts.
        win_h   = wins,
        lose_h  = losses,
        win_y0  = y1 - win_h,
        win_y1  = y1,
        lose_y0 = y0,
        lose_y1 = y0 + lose_h
    ) %>%
    ungroup()

# Aligned ribbons: each link's win (green) sub-ribbon connects between the
# green rects of source and target, and the lose (red) sub-ribbon connects
# between the red rects.  Slice heights are exact (no scaling) since under
# the mutually-exclusive col-3 masks every node's outgoing and incoming
# totals match its node total.
build_ribbon_polys_aligned <- function(links, node_rects, n_seg = 80) {
    src_win_cur  <- setNames(node_rects$win_y1,  node_rects$id)
    src_lose_cur <- setNames(node_rects$lose_y1, node_rects$id)
    tgt_win_cur  <- setNames(node_rects$win_y1,  node_rects$id)
    tgt_lose_cur <- setNames(node_rects$lose_y1, node_rects$id)

    out <- vector("list", nrow(links) * 2)
    k <- 0
    for (i in seq_len(nrow(links))) {
        if (links$count[i] <= 0) next
        s <- links$src[i]; t <- links$tgt[i]
        w <- links$wins[i]; l <- links$losses[i]
        x_seq <- seq(links$src_x[i], links$tgt_x[i], length.out = n_seg)
        tt    <- (x_seq - links$src_x[i]) / (links$tgt_x[i] - links$src_x[i])
        ss    <- smooth_step(tt)

        if (w > 0) {
            sy_top <- src_win_cur[s]; sy_bot <- sy_top - w
            ty_top <- tgt_win_cur[t]; ty_bot <- ty_top - w
            src_win_cur[s] <- sy_bot
            tgt_win_cur[t] <- ty_bot
            y_top <- sy_top + (ty_top - sy_top) * ss
            y_bot <- sy_bot + (ty_bot - sy_bot) * ss
            k <- k + 1
            out[[k]] <- data.frame(
                link_id = i, outcome = "win",
                x = c(x_seq, rev(x_seq)),
                y = c(y_top, rev(y_bot))
            )
        }
        if (l > 0) {
            sy_top <- src_lose_cur[s]; sy_bot <- sy_top - l
            ty_top <- tgt_lose_cur[t]; ty_bot <- ty_top - l
            src_lose_cur[s] <- sy_bot
            tgt_lose_cur[t] <- ty_bot
            y_top <- sy_top + (ty_top - sy_top) * ss
            y_bot <- sy_bot + (ty_bot - sy_bot) * ss
            k <- k + 1
            out[[k]] <- data.frame(
                link_id = i, outcome = "lose",
                x = c(x_seq, rev(x_seq)),
                y = c(y_top, rev(y_bot))
            )
        }
    }
    bind_rows(out[seq_len(k)])
}
ribbons_aligned <- build_ribbon_polys_aligned(links, node_rects)

# --- Plotting. -------------------------------------------------------------
WIN_FILL  <- "#1a9850"
LOSE_FILL <- "#b30000"

build_plot <- function(bg, fg, theme_fn, ribbon_color = "grey45",
                       ribbon_alpha = 0.35, ribbon_mode = "single") {
    # Column header positions a bit above the highest node top.
    col_headers <- tibble::tibble(
        col   = 1:4,
        x     = COL_X,
        label = c("Pantheon", "Religion Founded",
                  "Enhanced / Reformed", "End")
    )
    y_top_nodes <- max(nodes$y1)
    y_bot_nodes <- min(nodes$y0)
    span        <- y_top_nodes - y_bot_nodes
    header_y    <- y_top_nodes + 0.15 * span
    y_max       <- header_y + 0.05 * span
    y_min       <- y_bot_nodes - 0.18 * span

    label_above <- node_rects %>%
        mutate(text = label, ly = y1 + 0.015 * span)
    label_below <- node_rects %>%
        mutate(
            text = sprintf("%s winrate", percent(winrate, accuracy = 0.1)),
            ly   = y0 - 0.015 * span
        )
    # In-rect labels: count goes inside the green (wins) and red (losses)
    # rectangles, centered.  Always rendered (overlay) even if the rect is
    # too short for the text to fit -- text simply spills above/below.
    label_in_win  <- node_rects %>%
        filter(wins > 0) %>%
        mutate(ly = (win_y0 + win_y1) / 2,
               text = format(wins, big.mark = ","))
    label_in_lose <- node_rects %>%
        filter(losses > 0) %>%
        mutate(ly = (lose_y0 + lose_y1) / 2,
               text = format(losses, big.mark = ","))

    ribbon_layer <- if (ribbon_mode == "split") {
        list(
            geom_polygon(data = ribbons_split %>% filter(outcome == "lose"),
                         aes(x = x, y = y, group = link_id),
                         fill = "#f0a0a0", color = NA, alpha = 0.85),
            geom_polygon(data = ribbons_split %>% filter(outcome == "win"),
                         aes(x = x, y = y, group = link_id),
                         fill = "#a6dba0", color = NA, alpha = 0.85)
        )
    } else if (ribbon_mode == "aligned") {
        list(
            geom_polygon(data = ribbons_aligned %>% filter(outcome == "lose"),
                         aes(x = x, y = y, group = link_id),
                         fill = "#f0a0a0", color = NA, alpha = 0.85),
            geom_polygon(data = ribbons_aligned %>% filter(outcome == "win"),
                         aes(x = x, y = y, group = link_id),
                         fill = "#a6dba0", color = NA, alpha = 0.85)
        )
    } else {
        list(
            geom_polygon(data = ribbons,
                         aes(x = x, y = y, group = link_id),
                         fill = ribbon_color, color = NA, alpha = ribbon_alpha)
        )
    }

    ggplot() +
        # Ribbons under the nodes.
        ribbon_layer +
        # Ribbon annotations.
        geom_segment(data = ribbon_leaders,
                     aes(x = x, y = y, xend = xend, yend = yend),
                     color = fg, linewidth = 0.3, alpha = 0.7,
                     arrow = arrow(length = unit(6, "pt"), type = "closed")) +
        geom_text(data = ribbon_labels,
                  aes(x = x, y = y, label = text),
                  color = fg, fontface = "italic", size = 3.4,
                  lineheight = 0.95, vjust = 1) +
        # Loss (red) rects.
        geom_rect(data = node_rects,
                  aes(xmin = xl, xmax = xr, ymin = lose_y0, ymax = lose_y1),
                  fill = LOSE_FILL, color = bg, linewidth = 0.4) +
        # Win (green) rects.
        geom_rect(data = node_rects,
                  aes(xmin = xl, xmax = xr, ymin = win_y0, ymax = win_y1),
                  fill = WIN_FILL, color = bg, linewidth = 0.4) +
        # In-rect: wins count inside green.
        geom_text(data = label_in_win,
                  aes(x = x, y = ly, label = text),
                  color = "white", fontface = "bold", size = 3.6) +
        # In-rect: losses count inside red.
        geom_text(data = label_in_lose,
                  aes(x = x, y = ly, label = text),
                  color = "white", fontface = "bold", size = 3.6) +
        # Node names above.
        geom_text(data = label_above,
                  aes(x = x, y = ly, label = text),
                  color = fg, fontface = "bold", size = 4.0,
                  vjust = 0, lineheight = 0.95) +
        # Stats below.
        geom_text(data = label_below,
                  aes(x = x, y = ly, label = text),
                  color = fg, size = 3.4, vjust = 1, lineheight = 1.0) +
        # Column headers at top.
        geom_text(data = col_headers,
                  aes(x = x, y = header_y, label = label),
                  color = fg, fontface = "bold", size = 5.4, vjust = 0.5) +
        coord_cartesian(xlim = c(0.4, 4.6), ylim = c(y_min, y_max),
                        clip = "off") +
        labs(title = "Religious Attainment Game Results",
             x = NULL, y = NULL) +
        theme_fn(base_size = 13) +
        theme(
            plot.title       = element_text(face = "bold", size = 18,
                                            color = fg),
            plot.subtitle    = element_text(size = 12, color = fg,
                                            margin = margin(b = 8)),
            plot.background  = element_rect(fill = bg, color = bg),
            panel.background = element_rect(fill = bg, color = bg),
            panel.grid       = element_blank(),
            panel.grid.major = element_blank(),
            panel.grid.minor = element_blank(),
            panel.grid.major.x = element_blank(),
            panel.grid.major.y = element_blank(),
            axis.text        = element_blank(),
            axis.text.x      = element_blank(),
            axis.text.y      = element_blank(),
            axis.ticks       = element_blank(),
            axis.ticks.x     = element_blank(),
            axis.ticks.y     = element_blank(),
            axis.title       = element_blank(),
            axis.title.x     = element_blank(),
            axis.title.y     = element_blank(),
            axis.line        = element_blank(),
            axis.line.x      = element_blank(),
            axis.line.y      = element_blank()
        )
}

p_a <- build_plot(IPSUM_VP_BG,      "grey20",         theme_report,
                  ribbon_color = "grey40", ribbon_alpha = 0.30)
save_plot(p_a, "18a_religion_sankey", width = 14, height = 9)

p_b <- build_plot(IPSUM_VP_DARK_BG, IPSUM_VP_DARK_FG, theme_report_dark,
                  ribbon_color = "grey70", ribbon_alpha = 0.30)
save_plot_dark(p_b, "18b_religion_sankey", width = 14, height = 9)

# Split-ribbon variants: pale green (wins) on top, pale red (losses) below
# within each ribbon.
p_c <- build_plot(IPSUM_VP_BG,      "grey20",         theme_report,
                  ribbon_mode = "split")
save_plot(p_c, "18c_religion_sankey_split", width = 14, height = 9)

p_d <- build_plot(IPSUM_VP_DARK_BG, IPSUM_VP_DARK_FG, theme_report_dark,
                  ribbon_mode = "split")
save_plot_dark(p_d, "18d_religion_sankey_split", width = 14, height = 9)

# Aligned-ribbon variants: green sub-ribbons connect green rect -> green rect,
# red sub-ribbons connect red rect -> red rect.
p_e <- build_plot(IPSUM_VP_BG,      "grey20",         theme_report,
                  ribbon_mode = "aligned")
save_plot(p_e, "18e_religion_sankey_aligned", width = 14, height = 9)

p_f <- build_plot(IPSUM_VP_DARK_BG, IPSUM_VP_DARK_FG, theme_report_dark,
                  ribbon_mode = "aligned")
save_plot_dark(p_f, "18f_religion_sankey_aligned", width = 14, height = 9)
