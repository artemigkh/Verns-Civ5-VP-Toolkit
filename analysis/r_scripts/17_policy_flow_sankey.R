# 17: Policy-branch flow per civ -- Sankey/alluvial across the 4 tiers
#     (Ancient -> Medieval -> Industrial -> Modern). Outputs:
#       output/r_plots/light/policy_flow/_all_civs.png  (light theme)
#       output/r_plots/light/policy_flow/<civ>.png
#       output/r_plots/dark/policy_flow/_all_civs.png   (dark  theme)
#       output/r_plots/dark/policy_flow/<civ>.png
source("r_scripts/common.R")
suppressPackageStartupMessages(library(ggalluvial))

policy_df <- load_spark_csv("policy_choices")
policy_df <- synth_clone_per_game(policy_df, "policy_df")

BRANCH_NAMES <- c(
    "Tradition", "Progress", "Authority",
    "Fealty",    "Statecraft", "Artistry",
    "Industry",  "Imperialism", "Rationalism",
    "Freedom",   "Order",       "Autocracy"
)
TIER_NAMES <- c("Ancient", "Medieval", "Industrial", "Modern")

# Each (game_id, civ) timeline: every "Branch N" pick records the FIRST branch
# they opened in that tier.
branch_picks <- policy_df %>%
    mutate(item = as.character(item),
           branch_marker = suppressWarnings(
               as.integer(stringr::str_match(item, "^Branch (\\d+)$")[, 2])
           ),
           pick_order = as.integer(pick_order)) %>%
    filter(!is.na(branch_marker), branch_marker >= 0, branch_marker <= 11) %>%
    transmute(game_id, civ,
              tier   = branch_marker %/% 3 + 1,
              branch = BRANCH_NAMES[branch_marker + 1],
              pick_order)

# If a civ opens 2 branches in the same tier (rare), keep the first one.
first_in_tier <- branch_picks %>%
    arrange(game_id, civ, tier, pick_order) %>%
    distinct(game_id, civ, tier, .keep_all = TRUE) %>%
    select(game_id, civ, tier, branch)

# Color palette: 12 visually distinct hues (one per branch). Within a tier
# the three branches are deliberately different hues so flows leaving the
# same tier remain easy to tell apart.
branch_colors <- c(
    Tradition   = "#1b9e77",  # teal
    Progress    = "#7570b3",  # purple
    Authority   = "#d95f02",  # orange
    Fealty      = "#e7298a",  # magenta
    Statecraft  = "#66a61e",  # green
    Artistry    = "#e6ab02",  # gold
    Industry    = "#a6761d",  # brown
    Imperialism = "#666666",  # grey
    Rationalism = "#1f78b4",  # blue
    Freedom     = "#33a02c",  # leaf green
    Order       = "#cb181d",  # red
    Autocracy   = "#6a3d9a"   # deep purple
)

# Pick black/white text per fill colour for legibility.
luminance <- function(hex) {
    rgb <- col2rgb(hex) / 255
    drop(t(rgb) %*% c(0.2126, 0.7152, 0.0722))
}
branch_text_colors <- ifelse(luminance(branch_colors) > 0.55,
                             "grey10", "white")
names(branch_text_colors) <- names(branch_colors)

# Stratum factor levels: invisible bottom + top pads sandwich the real
# branches so each axis can be vertically centered.
PAD_BOT      <- "__pad_bot__"
PAD_TOP      <- "__pad_top__"
STRATUM_LVLS <- c(PAD_BOT, BRANCH_NAMES, PAD_TOP)
PAD_FILL     <- setNames(c(NA_character_, NA_character_), c(PAD_BOT, PAD_TOP))
PAD_TEXT     <- setNames(c(NA_character_, NA_character_), c(PAD_BOT, PAD_TOP))

# Long/lodes form. Every (game, civ) appears at every axis. If they don't
# have a real branch in a tier, they get routed into a transparent
# PAD_BOT or PAD_TOP stratum -- per source half goes to BOT and half to
# TOP, so the connecting ribbon leaving every source block is centered
# vertically on that block. PAD strata are NA-filled and the pad flows
# are alpha=0, so drop-outs are invisible.
make_alluvial <- function(df, title, theme_fn, bg, with_caption = TRUE) {
    if (nrow(df) == 0) return(ggplot() + labs(title = title))

    real_long <- df %>%
        mutate(id = paste(game_id, civ, sep = "__")) %>%
        select(id, tier, branch)

    pairs <- distinct(real_long, id)

    all_pt <- tidyr::crossing(pairs, tier = 1:4) %>%
        left_join(real_long, by = c("id", "tier"))

    # First missing tier per pair (and the source branch immediately
    # before it, if any). Side (BOT/TOP) is fixed at this drop-out event
    # and inherited for every subsequent missing tier, so a dropped-out
    # pair stays on the same side across axes (no crossings).
    first_miss <- all_pt %>%
        filter(is.na(branch)) %>%
        arrange(id, tier) %>%
        group_by(id) %>%
        slice_head(n = 1) %>%
        ungroup() %>%
        select(id, first_miss_tier = tier)

    prior_src <- first_miss %>%
        left_join(real_long, by = "id") %>%
        filter(is.na(tier) | tier < first_miss_tier) %>%
        group_by(id, first_miss_tier) %>%
        summarise(
            prior_branch = if (any(!is.na(tier)))
                              branch[which.max(replace(tier, is.na(tier), -1L))]
                           else NA_character_,
            prior_tier   = if (any(!is.na(tier)))
                              max(tier, na.rm = TRUE)
                           else NA_integer_,
            .groups = "drop"
        )

    sides <- prior_src %>%
        group_by(prior_branch, prior_tier, first_miss_tier) %>%
        arrange(id, .by_group = TRUE) %>%
        mutate(rank     = row_number(),
               total    = n(),
               pad_side = if_else(rank <= total / 2, PAD_BOT, PAD_TOP)) %>%
        ungroup() %>%
        select(id, pad_side)

    long <- all_pt %>%
        left_join(sides, by = "id") %>%
        mutate(stratum_chr = if_else(is.na(branch), pad_side, branch),
               stratum     = factor(stratum_chr, levels = STRATUM_LVLS),
               x           = factor(TIER_NAMES[tier], levels = TIER_NAMES),
               y           = 1L) %>%
        select(id, x, tier, stratum, y)

    # Per-flow alpha: only real -> real flows are visible. Drop-out flows
    # (real -> pad, pad -> pad, pad -> real) are alpha=0 so the visible
    # ribbon between two real strata is centered on its source block.
    long <- long %>%
        arrange(id, tier) %>%
        group_by(id) %>%
        mutate(next_stratum = lead(as.character(stratum))) %>%
        ungroup() %>%
        mutate(flow_alpha = if_else(
            !is.na(next_stratum) &
                as.character(stratum) %in% BRANCH_NAMES &
                next_stratum         %in% BRANCH_NAMES,
            0.6, 0))

    ggplot(long,
           aes(x = x, stratum = stratum, alluvium = id, y = y)) +
        geom_flow(aes(fill = stratum, alpha = flow_alpha),
                  curve_type = "sigmoid",
                  width = 1/3, knot.pos = 0.4,
                  aes.flow = "forward",
                  decreasing = NA) +
        geom_stratum(aes(fill = stratum),
                     width = 1/3, color = bg, linewidth = 2.5,
                     decreasing = NA) +
        geom_text(stat = "stratum",
                  aes(label = ifelse(
                          as.character(after_stat(stratum)) %in%
                              c(PAD_BOT, PAD_TOP),
                          "", as.character(after_stat(stratum))),
                      color = after_stat(stratum)),
                  size = 3.4, fontface = "bold",
                  decreasing = NA) +
        scale_x_discrete(expand = c(0.05, 0.05), position = "top") +
        scale_y_continuous(expand = expansion(mult = c(0, 0.02))) +
        scale_fill_manual(values = c(branch_colors, PAD_FILL),
                          na.value = NA, guide = "none") +
        scale_color_manual(values = c(branch_text_colors, PAD_TEXT),
                           na.value = NA, guide = "none") +
        scale_alpha_identity() +
        labs(title = title,
             caption = if (with_caption) default_caption() else NULL,
             x = NULL, y = "Civ-games") +
        theme_fn(base_size = 12) +
        theme(panel.grid       = element_blank(),
              panel.background = element_rect(fill = bg, color = NA),
              axis.text.x.top  = element_text(face = "bold", size = 12),
              axis.ticks.x     = element_blank(),
              axis.text.y      = element_blank(),
              axis.ticks.y     = element_blank(),
              plot.caption     = element_text(size = 11, hjust = 1,
                                              face = "italic"))
}

# Save under a subdirectory; one tree per variant.
save_flow <- function(p, name, out_dir, bg, height = 9, width = 12) {
    path <- file.path(out_dir, paste0(name, ".png"))
    ggsave(path, p, width = width, height = height, dpi = 150, bg = bg)
    cat("saved:", path, "\n")
}

render_variant <- function(variant) {
    if (variant == "a") {
        out_dir <- file.path(OUTPUT_DIR_LIGHT, "policy_flow")
        theme_fn <- theme_report
        bg <- IPSUM_VP_BG
    } else {
        out_dir <- file.path(OUTPUT_DIR_DARK, "policy_flow")
        theme_fn <- theme_report_dark
        bg <- IPSUM_VP_DARK_BG
    }
    dir.create(out_dir, showWarnings = FALSE, recursive = TRUE)

    save_flow(make_alluvial(first_in_tier,
                            "Policy Branch Flow - All Civilizations",
                            theme_fn, bg),
              "_all_civs", out_dir, bg, height = 10, width = 13)

    # No-caption variant used by composite 21 (which renders a single
    # caption at the bottom-right of the combined figure).
    save_flow(make_alluvial(first_in_tier,
                            "Policy Branch Flow - All Civilizations",
                            theme_fn, bg, with_caption = FALSE),
              "_all_civs_nocap", out_dir, bg, height = 10, width = 13)

    for (civ_name in sort(unique(first_in_tier$civ))) {
        sub_df <- first_in_tier %>% filter(civ == civ_name)
        if (nrow(sub_df) == 0) next
        safe <- stringr::str_replace_all(civ_name, "[^A-Za-z0-9]+", "_")
        save_flow(make_alluvial(sub_df,
                                paste0("Policy Branch Flow - ", civ_name),
                                theme_fn, bg, with_caption = FALSE),
                  safe, out_dir, bg)
    }
}

render_variant("a")
render_variant("b")
