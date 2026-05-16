# 21: "Policies Overview" composite (dark theme only).
#
# Layout (single PNG, vertical stack):
#   1. 15b-style policy-branch picks-per-civ table (orange gradient,
#      matching the vassalage heatmap accent).
#   2. Upside-down marginal bar chart: total times each branch was
#      opened across all (game, civ) pairs.
#   3. 16b-style "Wins by Policy Branch" stacked bars.
#   4. 16d-style "Win Rate by Policy Branch" stacked bars.
#   5. The all-civs policy-flow sankey, appended via {magick}.
#
# Panels 1-4 are built inline as a single patchwork column so the 12
# branch columns line up across the table, marginal, and both bar charts.
# Panel 5 is read from the already-rendered _all_civs.png and stacked
# below via image_append.
#
# Output:
#   output/r_plots/dark/composites/policies_overview.png
source("r_scripts/common.R")
suppressPackageStartupMessages(library(magick))

DARK_DIR <- file.path("output", "r_plots", "dark")
COMP_DIR <- file.path(DARK_DIR, "composites")
dir.create(COMP_DIR, recursive = TRUE, showWarnings = FALSE)

BG      <- IPSUM_VP_DARK_BG
FG      <- IPSUM_VP_DARK_FG
ORANGE  <- "#ff9900"   # same accent the vassalage heatmap uses
LUT     <- vtc_lut_b

BRANCH_NAMES <- c(
    "Tradition", "Progress", "Authority",
    "Fealty",    "Statecraft", "Artistry",
    "Industry",  "Imperialism", "Rationalism",
    "Freedom",   "Order",       "Autocracy"
)
sep_x <- c(3.5, 6.5, 9.5)  # tier separators

# ---------------------------------------------------------------------------
# Data: policy picks per civ x branch (mirrors 15).
# ---------------------------------------------------------------------------
policy_df <- load_spark_csv("policy_choices")
policy_df <- synth_clone_per_game(policy_df, "policy_df")

policy_df <- policy_df %>%
    mutate(pick_order = as.integer(pick_order),
           item       = as.character(item),
           branch_marker = suppressWarnings(
               as.integer(stringr::str_match(item, "^Branch (\\d+)$")[, 2])
           )) %>%
    arrange(game_id, civ, pick_order) %>%
    group_by(game_id, civ) %>%
    mutate(branch = zoo::na.locf(branch_marker, na.rm = FALSE)) %>%
    ungroup() %>%
    filter(!is.na(branch), branch >= 0, branch <= 11)

cell_df <- policy_df %>%
    count(civ, branch, name = "n") %>%
    tidyr::complete(civ, branch = 0:11, fill = list(n = 0)) %>%
    mutate(branch_name = factor(BRANCH_NAMES[branch + 1],
                                levels = BRANCH_NAMES),
           tier        = branch %/% 3) %>%
    group_by(civ, tier) %>%
    mutate(tier_total = sum(n),
           prop = ifelse(tier_total > 0, n / tier_total, 0)) %>%
    ungroup()

civ_levels <- sort(unique(cell_df$civ), decreasing = TRUE)
cell_df <- cell_df %>% mutate(civ = factor(civ, levels = civ_levels))

# ---------------------------------------------------------------------------
# Data: branch-level stats (mirrors 16 / 16-winrate).
# ---------------------------------------------------------------------------
branch_stats_df <- load_spark_csv("branch_stats")
branch_stats_df <- synth_clone_per_game(branch_stats_df, "branch_stats_df")

branch_filtered <- branch_stats_df %>%
    mutate(branch = as.integer(branch)) %>%
    filter(!is.na(branch), branch >= 0, branch <= 11) %>%
    mutate(branch_name = factor(BRANCH_NAMES[branch + 1],
                                levels = BRANCH_NAMES))

opens_per_branch <- branch_filtered %>%
    count(branch_name, .drop = FALSE, name = "opens")

wins_per_branch <- branch_filtered %>%
    filter(!is.na(victory_type), nzchar(as.character(victory_type))) %>%
    mutate(victory_type = factor(as.character(victory_type),
                                 levels = VICTORY_LEVELS)) %>%
    count(branch_name, victory_type, name = "wins")

present_vtypes <- wins_per_branch %>%
    group_by(victory_type) %>%
    summarise(total = sum(wins), .groups = "drop") %>%
    filter(total > 0) %>%
    pull(victory_type) %>%
    as.character()
wins_per_branch <- wins_per_branch %>%
    mutate(victory_type = factor(as.character(victory_type),
                                 levels = intersect(VICTORY_LEVELS,
                                                    present_vtypes)))

wins_totals <- wins_per_branch %>%
    group_by(branch_name) %>%
    summarise(total_wins = sum(wins), .groups = "drop")

winrate_long <- wins_per_branch %>%
    left_join(opens_per_branch, by = "branch_name") %>%
    mutate(winrate = ifelse(opens > 0, wins / opens, 0))

winrate_totals <- winrate_long %>%
    group_by(branch_name) %>%
    summarise(total_winrate = sum(winrate), .groups = "drop")

n_games_eff <- length(unique(branch_stats_df$game_id))
caption_text <- sprintf(
    "%d Civ5 VP autoplay games  -  Emperor difficulty",
    n_games_eff)

# ---------------------------------------------------------------------------
# Panel 1: orange policy-branch table.
# ---------------------------------------------------------------------------
panel_table <- ggplot(cell_df,
                     aes(x = branch_name, y = civ, fill = prop)) +
    geom_tile(color = "grey25", linewidth = 0.3) +
    geom_text(aes(label = ifelse(n == 0, "0", as.character(n))),
              size = 3.2, color = FG) +
    geom_vline(xintercept = sep_x, color = "grey55", linewidth = 0.7) +
    scale_fill_gradient(low = "#1f1b18", high = ORANGE,
                        limits = c(0, 1), guide = "none") +
    scale_x_discrete(position = "top", expand = c(0, 0),
                     limits = BRANCH_NAMES) +
    scale_y_discrete(expand = c(0, 0)) +
    labs(title = "Policies Chosen Per Civilization, By Branch",
         x = NULL, y = NULL) +
    theme_report_dark(base_size = 12) +
    theme(panel.grid       = element_blank(),
          panel.background = element_rect(fill = BG, color = NA),
          axis.text.x.top  = element_text(angle = 90, hjust = 0, vjust = 0.5,
                                          face = "bold"),
          axis.text.y      = element_text(face = "bold"),
          axis.ticks       = element_blank())

# ---------------------------------------------------------------------------
# Panel 2: upside-down marginal bar -- total opens per branch.
# ---------------------------------------------------------------------------
panel_marginal <- ggplot(opens_per_branch,
                        aes(x = branch_name, y = opens)) +
    geom_col(fill = ORANGE, width = 0.78) +
    geom_text(aes(label = opens),
              vjust = -0.3, size = 3.2, color = FG, fontface = "bold") +
    geom_vline(xintercept = sep_x, color = "grey55", linewidth = 0.7) +
    scale_x_discrete(limits = BRANCH_NAMES, expand = c(0, 0)) +
    scale_y_reverse(expand = expansion(mult = c(0.25, 0))) +
    labs(title = "Total Branch Opens", x = NULL, y = NULL) +
    theme_report_dark(base_size = 12) +
    theme(
        axis.text.x        = element_blank(),
        axis.ticks.x       = element_blank(),
        axis.text.y        = element_blank(),
        axis.ticks.y       = element_blank(),
        panel.grid.major.x = element_blank(),
        panel.grid.major.y = element_blank(),
        plot.title         = element_text(face = "bold", size = 12,
                                          hjust = 0.5, color = FG)
    )

# ---------------------------------------------------------------------------
# Panel 3: 16b-style wins bars.
# ---------------------------------------------------------------------------
panel_wins <- ggplot(wins_per_branch,
                    aes(x = branch_name, y = wins, fill = victory_type)) +
    geom_col(width = 0.78, color = BG, linewidth = 0.25) +
    geom_text(data = wins_totals,
              aes(x = branch_name, y = total_wins, label = total_wins),
              inherit.aes = FALSE,
              vjust = -0.4, size = 3.4, color = FG) +
    scale_x_discrete(limits = BRANCH_NAMES) +
    scale_fill_manual(values = LUT, name = "Victory type") +
    scale_y_continuous(expand = expansion(mult = c(0, 0.10))) +
    labs(title = "Wins by Policy Branch",
         x = NULL, y = "Wins") +
    theme_report_dark(base_size = 12) +
    theme(
        axis.text.x        = element_blank(),
        axis.ticks.x       = element_blank(),
        panel.grid.major.x = element_blank()
    )

# ---------------------------------------------------------------------------
# Panel 4: 16d-style win-rate bars.
# ---------------------------------------------------------------------------
panel_winrate <- ggplot(winrate_long,
                       aes(x = branch_name, y = winrate, fill = victory_type)) +
    geom_col(width = 0.78, color = BG, linewidth = 0.25) +
    geom_text(data = winrate_totals,
              aes(x = branch_name, y = total_winrate,
                  label = percent(total_winrate, accuracy = 1)),
              inherit.aes = FALSE,
              vjust = -0.2, size = 3.2, color = FG) +
    scale_x_discrete(limits = BRANCH_NAMES) +
    scale_fill_manual(values = LUT, name = "Victory type", drop = FALSE) +
    scale_y_continuous(labels = percent_format(accuracy = 1),
                       expand = expansion(mult = c(0, 0.18))) +
    labs(title = "Win Rate by Policy Branch",
         caption = caption_text,
         x = "Policy branch", y = "Win rate") +
    theme_report_dark(base_size = 12) +
    theme(
        axis.text.x        = element_text(angle = 45, hjust = 1, vjust = 1,
                                          size = 10),
        panel.grid.major.x = element_blank(),
        plot.caption       = element_text(color = FG, size = 11,
                                          hjust = 1, face = "italic")
    )

# ---------------------------------------------------------------------------
# Patchwork stack of panels 1-4 with one shared legend for 3 and 4.
# ---------------------------------------------------------------------------
n_civs <- length(civ_levels)
table_h    <- max(10, 0.32 * n_civs + 3)  # same formula as script 15
marginal_h <- 1.5
wins_h     <- 5.5
winrate_h  <- 6.0
top_total_h <- table_h + marginal_h + wins_h + winrate_h

top_stack <- (panel_table /
              panel_marginal /
              panel_wins /
              panel_winrate) +
    plot_layout(
        ncol = 1,
        heights = c(table_h, marginal_h, wins_h, winrate_h),
        guides  = "collect"
    ) &
    theme(legend.position = "bottom",
          legend.background = element_rect(fill = BG, color = BG))

TOP_PATH <- file.path(COMP_DIR, "_policies_overview_top.png")
ggsave(TOP_PATH, top_stack, width = 14, height = top_total_h,
       dpi = 150, bg = BG, limitsize = FALSE)
cat("saved:", TOP_PATH, "\n")

# ---------------------------------------------------------------------------
# Stack: top patchwork | all-civs policy flow sankey.
# ---------------------------------------------------------------------------
read_img <- function(path) {
    if (!file.exists(path)) stop("Missing image: ", path)
    image_read(path)
}

ptop    <- read_img(TOP_PATH)
psankey <- read_img(file.path(DARK_DIR, "policy_flow", "_all_civs.png"))

imgs <- c(ptop, psankey)
target_w <- max(image_info(imgs)$width)
scaled <- lapply(seq_along(imgs), function(i) {
    image_scale(imgs[i], paste0(target_w, "x"))
})
composite <- image_append(do.call(c, scaled), stack = TRUE)

OUT_PATH <- file.path(COMP_DIR, "policies_overview.png")
image_write(composite, OUT_PATH, format = "png")
cat("saved:", OUT_PATH, "\n")

unlink(TOP_PATH)
