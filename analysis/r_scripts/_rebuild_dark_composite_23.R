# Targeted rebuild: dark composite only for script 23.
# Skips the per-civilization loop; only regenerates all_civs_unit_composition.png (dark).
# Run from the analysis/ directory: Rscript r_scripts/_rebuild_dark_composite_23.R

source("r_scripts/common.R")

# ---------------------------------------------------------------------------
# Build unit display-name, minimum-era, and colour-category lookups.
# ---------------------------------------------------------------------------
GRIDX_TO_ERA_MAP <- c(
    "1"  = 1,  # Ancient
    "2"  = 1,  # Ancient
    "3"  = 2,  # Classical
    "4"  = 2,  # Classical
    "5"  = 3,  # Medieval
    "6"  = 3,  # Medieval
    "7"  = 4,  # Renaissance
    "8"  = 4,  # Renaissance
    "9"  = 5,  # Industrial
    "10" = 5,  # Industrial
    "11" = 6,  # Modern
    "12" = 6,  # Modern
    "13" = 7,  # Atomic
    "14" = 7,  # Atomic
    "15" = 8,  # Information
    "16" = 8,  # Information
    "17" = 9,  # Information
    "18" = 10  # Future
)

TECH_TO_GRIDX_MAP <- c(
    "TECH_AGRICULTURE"        = 0,
    "TECH_POTTERY"            = 1,
    "TECH_ANIMAL_HUSBANDRY"   = 1,
    "TECH_ARCHERY"            = 2,
    "TECH_MINING"             = 1,
    "TECH_SAILING"            = 2,
    "TECH_CALENDAR"           = 2,
    "TECH_WRITING"            = 3,
    "TECH_TRAPPING"           = 1,
    "TECH_THE_WHEEL"          = 1,
    "TECH_MASONRY"            = 2,
    "TECH_BRONZE_WORKING"     = 2,
    "TECH_OPTICS"             = 3,
    "TECH_HORSEBACK_RIDING"   = 2,
    "TECH_MATHEMATICS"        = 3,
    "TECH_CONSTRUCTION"       = 3,
    "TECH_PHILOSOPHY"         = 4,
    "TECH_DRAMA"              = 4,
    "TECH_CURRENCY"           = 4,
    "TECH_ENGINEERING"        = 4,
    "TECH_IRON_WORKING"       = 3,
    "TECH_THEOLOGY"           = 5,
    "TECH_CIVIL_SERVICE"      = 6,
    "TECH_GUILDS"             = 6,
    "TECH_METAL_CASTING"      = 4,
    "TECH_COMPASS"            = 6,
    "TECH_EDUCATION"          = 5,
    "TECH_CHIVALRY"           = 5,
    "TECH_MACHINERY"          = 6,
    "TECH_PHYSICS"            = 5,
    "TECH_STEEL"              = 5,
    "TECH_ASTRONOMY"          = 7,
    "TECH_ACOUSTICS"          = 8,
    "TECH_BANKING"            = 7,
    "TECH_PRINTING_PRESS"     = 7,
    "TECH_GUNPOWDER"          = 7,
    "TECH_NAVIGATION"         = 8,
    "TECH_ARCHITECTURE"       = 8,
    "TECH_ECONOMICS"          = 8,
    "TECH_METALLURGY"         = 8,
    "TECH_CHEMISTRY"          = 7,
    "TECH_ARCHAEOLOGY"        = 10,
    "TECH_SCIENTIFIC_THEORY"  = 9,
    "TECH_INDUSTRIALIZATION"  = 10,
    "TECH_RIFLING"            = 9,
    "TECH_MILITARY_SCIENCE"   = 10,
    "TECH_FERTILIZER"         = 10,
    "TECH_BIOLOGY"            = 11,
    "TECH_ELECTRICITY"        = 11,
    "TECH_STEAM_POWER"        = 9,
    "TECH_DYNAMITE"           = 10,
    "TECH_REFRIGERATION"      = 13,
    "TECH_RADIO"              = 12,
    "TECH_REPLACEABLE_PARTS"  = 11,
    "TECH_FLIGHT"             = 12,
    "TECH_RAILROAD"           = 9,
    "TECH_PLASTIC"            = 12,
    "TECH_ELECTRONICS"        = 14,
    "TECH_BALLISTICS"         = 12,
    "TECH_COMBUSTION"         = 11,
    "TECH_PENICILIN"          = 13,
    "TECH_ATOMIC_THEORY"      = 13,
    "TECH_RADAR"              = 14,
    "TECH_COMBINED_ARMS"      = 13,
    "TECH_ECOLOGY"            = 15,
    "TECH_NUCLEAR_FISSION"    = 14,
    "TECH_ROCKETRY"           = 13,
    "TECH_COMPUTERS"          = 14,
    "TECH_TELECOM"            = 15,
    "TECH_MOBILE_TACTICS"     = 15,
    "TECH_ADVANCED_BALLISTICS" = 15,
    "TECH_SATELLITES"         = 15,
    "TECH_ROBOTICS"           = 16,
    "TECH_LASERS"             = 16,
    "TECH_INTERNET"           = 16,
    "TECH_GLOBALIZATION"      = 17,
    "TECH_PARTICLE_PHYSICS"   = 17,
    "TECH_NUCLEAR_FUSION"     = 17,
    "TECH_NANOTECHNOLOGY"     = 17,
    "TECH_STEALTH"            = 16,
    "TECH_FUTURE_TECH"        = 18,
    "TECH_CORPORATIONS"       = 11
)

text_lut_df  <- read_csv("../db_util/out/text_lut.csv", show_col_types = FALSE)
text_lut_vec <- setNames(text_lut_df$Text, text_lut_df$Tag)

units_meta <- read_csv("../db_util/out/units.csv", show_col_types = FALSE) %>%
    select(Type, Domain, Description, PrereqTech, RangedCombat, IsMounted, MoveRate) %>%
    mutate(
        disp_name      = coalesce(text_lut_vec[Description], Type),
        prereq_gridx   = TECH_TO_GRIDX_MAP[PrereqTech],
        min_era        = as.integer(coalesce(GRIDX_TO_ERA_MAP[as.character(prereq_gridx)], 1)),
        ranged_combat  = replace_na(RangedCombat, 0),
        is_mounted     = replace_na(IsMounted, 0),
        unit_type      = case_when(
            Domain == "DOMAIN_AIR" ~ "Air",
            Domain == "DOMAIN_LAND" & is_mounted > 0 & ranged_combat > 0 ~ "Mounted ranged",
            Domain == "DOMAIN_LAND" & ranged_combat > 0 ~ "Land ranged",
            Domain == "DOMAIN_LAND" & MoveRate == "QUADRUPED" ~ "Mounted non-ranged",
            Domain == "DOMAIN_LAND" ~ "Land non-ranged",
            Domain == "DOMAIN_SEA"  & ranged_combat > 0 ~ "Sea ranged",
            Domain == "DOMAIN_SEA" ~ "Sea non-ranged",
            TRUE ~ "Unknown"
        )
    )

unit_disp_lut     <- setNames(units_meta$disp_name, units_meta$Type)
unit_min_era_lut  <- setNames(units_meta$min_era,   units_meta$Type)
unit_type_lut     <- setNames(units_meta$unit_type, units_meta$Type)

unit_display_name <- function(keys) coalesce(unit_disp_lut[keys], keys)
unit_min_era      <- function(keys) as.integer(coalesce(unit_min_era_lut[keys], 1))
unit_type         <- function(keys) coalesce(unit_type_lut[keys], "Unknown")

# ---------------------------------------------------------------------------
# Unit colour palettes.
# ---------------------------------------------------------------------------
UNIT_TYPE_LEGEND_LEVELS <- c("Land ranged", "Land non-ranged",
                             "Mounted ranged", "Mounted non-ranged",
                             "Sea ranged", "Sea non-ranged", "Air")
UNIT_TYPE_LEVELS <- c(UNIT_TYPE_LEGEND_LEVELS, "Unknown")
UNIT_TYPE_LABELS <- c(
    "Land ranged"     = "Ranged Infantry",
    "Land non-ranged" = "Melee Infantry",
    "Mounted ranged"  = "Ranged Cavalry",
    "Mounted non-ranged" = "Melee Cavalry",
    "Sea ranged"      = "Ranged Naval",
    "Sea non-ranged"  = "Melee Naval",
    "Air"             = "Air",
    "Unknown"         = "Unknown"
)
UNIT_TYPE_COLORS_DARK <- c(
    "Land ranged"     = "#90EE90",
    "Land non-ranged" = "#006400",
    "Mounted ranged"  = "#C49A6C",
    "Mounted non-ranged" = "#5C4033",
    "Sea ranged"      = "#87CEFA",
    "Sea non-ranged"  = "#00008B",
    "Air"             = "#A8B8C8",
    "Unknown"         = "#aaaaaa"
)

# ---------------------------------------------------------------------------
# Inline reorder_within / scale_x_reordered.
# ---------------------------------------------------------------------------
reorder_within <- function(x, by, within, ...) {
    stats::reorder(paste(x, within, sep = "___"), by, ...)
}
scale_x_reordered <- function(..., sep = "___") {
    reg <- paste0(sep, ".+$")
    ggplot2::scale_x_discrete(labels = function(x) gsub(reg, "", x), ...)
}

# ---------------------------------------------------------------------------
# Load and pre-process data.
# ---------------------------------------------------------------------------
unit_turn_df <- load_spark_csv("unit_compositions_turns")
era_turn_df  <- load_spark_csv("era_transitions") %>%
    group_by(game_id, civ, turn) %>%
    summarise(era = max(era, na.rm = TRUE), .groups = "drop")

era_counts <- era_turn_df %>%
    distinct(game_id, civ, era) %>%
    group_by(game_id, civ) %>%
    summarise(n_eras = n(), .groups = "drop")

single_era <- era_counts %>% filter(n_eras == 1)

if (nrow(single_era) > 0) {
    cat(sprintf("Removing %d civ-game instance(s) with only one era:\n", nrow(single_era)))
    era_turn_df  <- era_turn_df  %>% anti_join(single_era %>% select(game_id, civ), by = c("game_id", "civ"))
    unit_turn_df <- unit_turn_df %>% anti_join(single_era %>% select(game_id, civ), by = c("game_id", "civ"))
}

turn_denoms <- era_turn_df %>%
    group_by(civ, era) %>%
    summarise(civ_turn_instances = n(), .groups = "drop")

unit_turns_by_era <- unit_turn_df %>%
    inner_join(era_turn_df, by = c("game_id", "civ", "turn")) %>%
    mutate(min_era = unit_min_era(unit))

unit_turns_by_era <- unit_turns_by_era %>% filter(era >= min_era)

unit_summary_df <- unit_turns_by_era %>%
    group_by(civ, era, unit) %>%
    summarise(total_count = sum(count, na.rm = TRUE), .groups = "drop") %>%
    left_join(turn_denoms, by = c("civ", "era")) %>%
    mutate(mean_count = total_count / civ_turn_instances) %>%
    select(civ, era, unit, mean_count, total_count, civ_turn_instances) %>%
    filter(mean_count > 0.024)

# ---------------------------------------------------------------------------
# Output directory.
# ---------------------------------------------------------------------------
OUT_DIR_DARK <- file.path(OUTPUT_DIR_DARK, "unit_composition_by_era")
dir.create(OUT_DIR_DARK, recursive = TRUE, showWarnings = FALSE)

# ===========================================================================
# Composite: all civs x 9 fixed eras (Ancient through Future) — dark only
# ===========================================================================
COMPOSITE_ERAS <- c("Ancient", "Classical", "Medieval", "Renaissance", "Industrial",
                    "Modern", "Atomic", "Information", "Future")

composite_civs <- sort(unique(unit_summary_df$civ))
composite_panel_levels <- paste(
    rep(composite_civs, each = length(COMPOSITE_ERAS)),
    rep(COMPOSITE_ERAS, times = length(composite_civs)),
    sep = "\n"
)

composite_df <- unit_summary_df %>%
    mutate(
        era_label = era_lut[as.character(era)],
        unit_disp = unit_display_name(unit),
        unit_type = factor(unit_type(unit), levels = UNIT_TYPE_LEVELS)
    ) %>%
    filter(era_label %in% COMPOSITE_ERAS) %>%
    mutate(
        era_label = factor(era_label, levels = COMPOSITE_ERAS),
        civ       = factor(civ, levels = composite_civs)
    ) %>%
    group_by(civ, era_label) %>%
    slice_max(order_by = mean_count, n = 10, with_ties = FALSE) %>%
    ungroup() %>%
    mutate(
        panel_label = factor(
            paste(civ, era_label, sep = "\n"),
            levels = composite_panel_levels
        )
    )

max_units_per_civ <- composite_df %>%
    group_by(civ, era_label) %>%
    summarise(n_units = n(), .groups = "drop") %>%
    group_by(civ) %>%
    summarise(max_n = max(n_units), .groups = "drop")

row_h       <- max_units_per_civ$max_n * 0.20 + 1.0
comp_height <- sum(pmax(row_h, 1.5)) + 2.5
comp_width  <- length(COMPOSITE_ERAS) * 3.5  # 9 era columns

build_composite <- function(unit_colors, theme_fn, label_color, variant) {
    ggplot(composite_df,
           aes(x    = reorder_within(unit_disp, mean_count, panel_label),
               y    = mean_count,
               fill = unit_type)) +
        geom_col(show.legend = TRUE) +
        geom_text(aes(label = sprintf("%.1f", mean_count)),
                  hjust = -0.1, size = 1.6, color = label_color) +
        scale_fill_manual(values = unit_colors, breaks = UNIT_TYPE_LEGEND_LEVELS,
                          labels = UNIT_TYPE_LABELS[UNIT_TYPE_LEGEND_LEVELS],
                          drop = FALSE, name = "Unit type") +
        scale_x_reordered() +
        coord_flip() +
        facet_wrap(~ panel_label, scales = "free", ncol = length(COMPOSITE_ERAS),
               drop = FALSE) +
        scale_y_continuous(expand = expansion(mult = c(0, 0.30))) +
        labs(
            title   = "Unit Composition by Era \u2014 All Civilizations",
            caption = default_caption(n_games),
            x = NULL, y = NULL
        ) +
        theme_fn(base_size = 7) +
        theme(
            strip.text         = element_text(face = "bold", size = 6,
                                              color = label_color),
            panel.grid.major.y = element_blank(),
            axis.text.y        = element_text(size = 5, color = label_color),
            axis.text.x        = element_text(size = 4, color = label_color)
        ) +
        caption_theme(variant)
}

cat(sprintf("Composite canvas: %.1f x %.1f inches (%.0f x %.0f px at 120 dpi)\n",
            comp_width, comp_height, comp_width * 120, comp_height * 120))
options(ragg.max_dim = 200000)
cat("Building dark composite...\n")

p_comp_dark <- build_composite(UNIT_TYPE_COLORS_DARK, theme_report_dark, "white", "b")
ggsave(file.path(OUT_DIR_DARK, "all_civs_unit_composition.png"),
       p_comp_dark, width = comp_width, height = comp_height, dpi = 300,
       bg = IPSUM_VP_DARK_BG, limitsize = FALSE)
cat("Saved composite dark\n")
