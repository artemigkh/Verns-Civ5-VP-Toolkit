# 24: Win rate by player slot (position 1-8), with Goodman simultaneous CIs
# and chi-squared goodness-of-fit test.
# Raw game results are cached to intermediate_csvs/slot_wins/ on first run.
# Produces:
#   24a_winrate_by_slot.png  light theme
#   24b_winrate_by_slot.png  dark theme
source("r_scripts/common.R")

suppressPackageStartupMessages({
    library(purrr)
    library(RColorBrewer)
})

# -----------------------------------------------------------------------------
# 1. Load slot results from cache, or parse raw files and cache the result.
# -----------------------------------------------------------------------------
UNPACKED_ALL    <- Sys.getenv(
    "CIV5_UNPACKED_ALL",
    unset = file.path("..", "data", "MP_AUTOPLAY_VP_5_2_3", "unpacked", "all")
)
SLOT_CACHE_DIR  <- file.path(INTERMEDIATE_CSVS, "slot_wins")
SLOT_CACHE_FILE <- file.path(SLOT_CACHE_DIR, "slot_wins.csv")

if (file.exists(SLOT_CACHE_FILE)) {
    cat("Loading cached slot results from:", SLOT_CACHE_FILE, "\n")
    slot_results <- read_csv(SLOT_CACHE_FILE, show_col_types = FALSE,
                             progress = FALSE)
} else {
    game_files <- list.files(
        UNPACKED_ALL,
        pattern    = "GameResult_Log\\.csv\\.gz$",
        recursive  = TRUE,
        full.names = TRUE
    )
    if (length(game_files) == 0) {
        stop("No GameResult_Log.csv.gz files found under: ", UNPACKED_ALL)
    }

    parse_game_result <- function(path) {
        tryCatch({
            df <- read_csv(path, show_col_types = FALSE, trim_ws = TRUE,
                           progress = FALSE)
            names(df) <- trimws(names(df))
            if (nrow(df) == 0) return(NULL)
            row      <- df[1, ]
            victor   <- trimws(as.character(row[["VictoryCiv"]]))
            vtype    <- trimws(as.character(row[["VictoryType"]]))
            civ_cols <- trimws(names(df)[4:min(11, ncol(df))])
            slot     <- which(civ_cols == victor)
            if (length(slot) == 0) return(NULL)
            data.frame(slot = as.integer(slot[1]),
                       victory_type = vtype,
                       stringsAsFactors = FALSE)
        }, error = function(e) NULL)
    }

    cat(sprintf("Parsing %d game files...\n", length(game_files)))
    slot_results <- map_dfr(game_files, parse_game_result)
    cat(sprintf("Parsed %d valid game results.\n", nrow(slot_results)))

    dir.create(SLOT_CACHE_DIR, recursive = TRUE, showWarnings = FALSE)
    write_csv(slot_results, SLOT_CACHE_FILE)
    cat("Cached to:", SLOT_CACHE_FILE, "\n")
}

# -----------------------------------------------------------------------------
# 2. Aggregate wins and Goodman (1965) simultaneous 95% CIs.
# Goodman CIs use chi-squared critical value at alpha/k (1 df) to give
# simultaneous coverage across all k=8 categories.
# A slot is starred (*) when its CI excludes the null value 1/8.
# -----------------------------------------------------------------------------
n_total <- nrow(slot_results)
K       <- 8L
ALPHA   <- 0.05

slot_summary <- slot_results %>%
    count(slot, name = "wins") %>%
    right_join(data.frame(slot = 1:K), by = "slot") %>%
    mutate(wins = replace_na(wins, 0L))

# Goodman (1965): c = chi-sq quantile at 1 - alpha/k with 1 df
c_crit <- qchisq(1 - ALPHA / K, df = 1)

slot_summary <- slot_summary %>%
    mutate(
        winrate = wins / n_total,
        ci_lo   = pmax(0, (2 * n_total * winrate + c_crit -
                            sqrt(c_crit * (c_crit + 4 * n_total * winrate *
                                           (1 - winrate)))) /
                           (2 * (n_total + c_crit))),
        ci_hi   = pmin(1, (2 * n_total * winrate + c_crit +
                            sqrt(c_crit * (c_crit + 4 * n_total * winrate *
                                           (1 - winrate)))) /
                           (2 * (n_total + c_crit))),
        stars   = ifelse(ci_lo > 1 / K | ci_hi < 1 / K, "*", ""),
        slot    = factor(slot, levels = 1:K, labels = paste0("Slot ", 1:K))
    )

# -----------------------------------------------------------------------------
# 3. Chi-squared goodness-of-fit test (null: all slots win equally often).
# -----------------------------------------------------------------------------
chisq_result <- chisq.test(
    x = slot_summary$wins,
    p = rep(1 / 8, 8)
)
p_value  <- chisq_result$p.value
chi_stat <- chisq_result$statistic

p_label <- if (p_value < 0.001) {
    sprintf("Chi-squared = %.2f, p < 0.001 (n = %d)", chi_stat, n_total)
} else {
    sprintf("Chi-squared = %.2f, p = %.3f (n = %d)", chi_stat, p_value, n_total)
}
cat(p_label, "\n")

# Per-slot fill: Dark2 palette (8 distinct dark pastels)
SLOT_COLORS <- setNames(brewer.pal(8, "Dark2"), levels(slot_summary$slot))

# -----------------------------------------------------------------------------
# 4. Build plots (light + dark variants).
# -----------------------------------------------------------------------------
EXPECTED_WINRATE <- 1 / 8   # 0.125

build_slot_plot <- function(ref_color, text_color, err_color, theme_fn,
                            caption_col) {
    ggplot(slot_summary, aes(x = slot, y = winrate, fill = slot)) +
        geom_col(width = 0.7, color = NA) +
        geom_errorbar(aes(ymin = ci_lo, ymax = ci_hi),
                      width = 0.25, linewidth = 0.7, color = err_color) +
        geom_text(aes(label = scales::percent(winrate, accuracy = 0.1)),
                  vjust = 1.6, size = 3.4, color = text_color) +
        geom_text(aes(y = ci_hi, label = stars),
                  vjust = -0.3, size = 5.5, color = text_color) +
        geom_hline(yintercept = EXPECTED_WINRATE, linetype = "dashed",
                   color = ref_color, linewidth = 0.7) +
        annotate("text",
                 x = Inf, y = EXPECTED_WINRATE,
                 label = "expected (12.5%)",
                 hjust = 1.05, vjust = -0.55,
                 size = 3.4, color = ref_color, fontface = "italic") +
        scale_fill_manual(values = SLOT_COLORS, guide = "none") +
        scale_y_continuous(
            labels = scales::percent_format(accuracy = 1),
            expand = expansion(mult = c(0, 0.14))
        ) +
        theme_fn() +
        labs(
            title   = "Win Rate by Player Slot",
            x       = "Player Slot",
            y       = "Win rate",
            caption = sprintf("%s\n* Goodman 95%% simultaneous CI excludes 12.5%% null; overall %s",
                              default_caption(n = n_total), p_label)
        ) +
        theme(
            plot.caption = element_text(color = caption_col, size = 9,
                                        hjust = 1, face = "italic",
                                        margin = margin(t = 6))
        )
}

# Light variant (a)
p_light <- build_slot_plot(
    ref_color   = "grey40",
    text_color  = "grey10",
    err_color   = "grey30",
    theme_fn    = theme_report,
    caption_col = "grey45"
)
save_plot(p_light, "24a_winrate_by_slot", width = 9, height = 6)

# Dark variant (b)
p_dark <- build_slot_plot(
    ref_color   = "grey65",
    text_color  = IPSUM_VP_DARK_FG,
    err_color   = "grey75",
    theme_fn    = theme_report_dark,
    caption_col = "grey55"
)
save_plot_dark(p_dark, "24b_winrate_by_slot", width = 9, height = 6)
