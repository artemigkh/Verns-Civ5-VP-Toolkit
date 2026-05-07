# 12: Policy branch picks per civ -- table coloured by within-tier proportion.
source("r_scripts/common.R")

policy_df <- load_spark_csv("policy_choices")
policy_df <- synth_clone_per_game(policy_df, "policy_df")

BRANCH_NAMES <- c(
    "Tradition", "Progress", "Authority",
    "Fealty",    "Statecraft", "Artistry",
    "Industry",  "Imperialism", "Rationalism",
    "Freedom",   "Order",       "Autocracy"
)

# Each (game_id, civ) timeline: rows of "Branch N" mark the active tree;
# subsequent policy picks belong to that tree until another Branch row.
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
    mutate(branch_name = factor(BRANCH_NAMES[branch + 1], levels = BRANCH_NAMES),
           tier        = branch %/% 3)

# Within-civ within-tier (group of 3) proportion -> green shade intensity.
cell_df <- cell_df %>%
    group_by(civ, tier) %>%
    mutate(tier_total = sum(n),
           prop = ifelse(tier_total > 0, n / tier_total, 0)) %>%
    ungroup()

# Order civs alphabetically, top-down (so first civ ends at top of plot).
civ_levels <- sort(unique(cell_df$civ), decreasing = TRUE)
cell_df <- cell_df %>% mutate(civ = factor(civ, levels = civ_levels))

# Vertical separators between tiers (after columns 3, 6, 9).
sep_x <- c(3.5, 6.5, 9.5)

build_policy_table <- function(theme_fn, bg, tile_outline, text_color,
                               sep_color, low_color) {
    ggplot(cell_df, aes(x = branch_name, y = civ, fill = prop)) +
        geom_tile(color = tile_outline, linewidth = 0.3) +
        geom_text(aes(label = ifelse(n == 0, "0", as.character(n))),
                  size = 3.2, color = text_color) +
        geom_vline(xintercept = sep_x, color = sep_color, linewidth = 0.7) +
        scale_fill_gradient(low = low_color, high = "#1a9850",
                            limits = c(0, 1), guide = "none") +
        scale_x_discrete(position = "top", expand = c(0, 0)) +
        scale_y_discrete(expand = c(0, 0)) +
        labs(title = "Policies Chosen Per Civilization, By Branch",
             x = NULL, y = NULL) +
        theme_fn(base_size = 12) +
        theme(panel.grid       = element_blank(),
              panel.background = element_rect(fill = bg, color = NA),
              axis.text.x.top  = element_text(angle = 90, hjust = 0, vjust = 0.5,
                                              face = "bold"),
              axis.text.y      = element_text(face = "bold"),
              axis.ticks       = element_blank())
}

n_civs <- length(civ_levels)
save_plot(build_policy_table(theme_report, IPSUM_VP_BG,
                             tile_outline = "grey80", text_color = "grey15",
                             sep_color = "grey25", low_color = "white"),
          "12a_policy_branch_table",
          width = 12, height = max(10, 0.32 * n_civs + 3))
save_plot_dark(build_policy_table(theme_report_dark, IPSUM_VP_DARK_BG,
                                  tile_outline = "grey25",
                                  text_color = IPSUM_VP_DARK_FG,
                                  sep_color = "grey55",
                                  low_color = IPSUM_VP_DARK_BG),
               "12b_policy_branch_table",
               width = 12, height = max(10, 0.32 * n_civs + 3))
