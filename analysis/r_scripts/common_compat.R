# =============================================================================
# common_compat.R -- shim for running the canonical r_scripts/* against an
# older / alternate intermediate-CSV dataset (e.g. the WSL log processor
# output at ~/IdeaProjects/civ5-analytics/civ5-log-processor-output).
#
# Strategy: set env vars BEFORE sourcing common.R so the data dir, output
# dirs, and caption version strings are all overridden. Schemas appear
# identical for game_result / power_ranking / authority_victories / wonders
# / branch_stats / policy_choices, so no per-script data fixups are
# currently required. Any future schema drift fixes should be applied as
# additive post-source patches here (e.g. column renames, type coercions)
# rather than forking every script.
#
# Environment variables consumed by common.R:
#   CIV5_INTERMEDIATE_CSVS   absolute path to the intermediate_csvs root
#   CIV5_OUTPUT_DIR_LIGHT    where the *_a/*.png plots go
#   CIV5_OUTPUT_DIR_DARK     where the *_b/*.png plots go
#   CIV5_VP_VERSION          caption tag, e.g. "earlier" or "5.2.x"
#   CIV5_COMMUNITU_VERSION   caption tag, e.g. "earlier"
#
# `CIV5_COMPAT_DATA_DIR` may be set by the calling script as a portable
# alias (Windows UNC or POSIX); this file forwards it to
# CIV5_INTERMEDIATE_CSVS if the latter isn't already set.
# =============================================================================

# Default path: the WSL log-processor output, accessed via UNC from a
# Windows R session. Override with CIV5_COMPAT_DATA_DIR if you want to
# point at a different dataset.
default_compat_dir <- if (.Platform$OS.type == "windows") {
    "//wsl.localhost/Ubuntu/home/art/IdeaProjects/civ5-analytics/civ5-log-processor-output"
} else {
    "~/IdeaProjects/civ5-analytics/civ5-log-processor-output"
}

compat_dir <- Sys.getenv("CIV5_COMPAT_DATA_DIR", unset = default_compat_dir)

if (Sys.getenv("CIV5_INTERMEDIATE_CSVS", unset = "") == "") {
    Sys.setenv(CIV5_INTERMEDIATE_CSVS = compat_dir)
}

# Output dirs: nest under a `compat/` folder so canonical-run outputs are
# never clobbered. Allow override via env.
if (Sys.getenv("CIV5_OUTPUT_DIR_LIGHT", unset = "") == "") {
    Sys.setenv(CIV5_OUTPUT_DIR_LIGHT = file.path("output", "r_plots",
                                                 "compat", "light"))
}
if (Sys.getenv("CIV5_OUTPUT_DIR_DARK", unset = "") == "") {
    Sys.setenv(CIV5_OUTPUT_DIR_DARK = file.path("output", "r_plots",
                                                "compat", "dark"))
}

# Caption tag: leave the version blank-but-explicit so plots are obviously
# from the older dataset. Override per-run if the exact version is known.
if (Sys.getenv("CIV5_VP_VERSION", unset = "") == "") {
    Sys.setenv(CIV5_VP_VERSION = "4.15.2-4UC")
}
if (Sys.getenv("CIV5_COMMUNITU_VERSION", unset = "") == "") {
    Sys.setenv(CIV5_COMMUNITU_VERSION = "3.2.0")
}

cat("compat: reading from", Sys.getenv("CIV5_INTERMEDIATE_CSVS"), "\n")
cat("compat: writing to",   Sys.getenv("CIV5_OUTPUT_DIR_LIGHT"),
    "and",                   Sys.getenv("CIV5_OUTPUT_DIR_DARK"), "\n")

source("r_scripts/common.R")

# -----------------------------------------------------------------------------
# Post-source defensive fixups for older intermediate-CSV layouts.
# Keep these additive -- the canonical-dataset run must remain unaffected
# whenever this file is NOT sourced. Each block describes what older data
# quirk it guards against so it's safe to delete once a dataset is
# normalised.
# -----------------------------------------------------------------------------

# 1) Older `power_ranking` rows occasionally store `winrate` and the
#    pct_* columns as strings with stray whitespace or "NaN". Coerce
#    numerically up front so downstream `as.numeric()` calls don't warn
#    and so empty-string cells don't propagate NA into bar heights.
.numericify <- function(x) {
    if (is.numeric(x)) return(x)
    suppressWarnings(as.numeric(trimws(as.character(x))))
}
.pr_numeric_cols <- intersect(
    c("count_games", "winrate",
      "culture_victories", "diplomatic_victories", "domination_victories",
      "science_victories", "time_victories",
      "pct_culture_victories", "pct_diplomatic_victories",
      "pct_domination_victories", "pct_science_victories",
      "pct_time_victories",
      "avg_tiles_owned_percentage", "avg_cities_owned_percentage",
      "avg_score"),
    names(power_ranking_df)
)
power_ranking_df <- power_ranking_df %>%
    mutate(across(all_of(.pr_numeric_cols), .numericify),
           across(all_of(.pr_numeric_cols), ~ tidyr::replace_na(.x, 0)))

# 2) Older `game_result` victory_type values sometimes leak through with
#    leading/trailing whitespace or unexpected casing ("DOMINATION" etc.).
#    Normalise to the canonical title-case factor levels used by every
#    plot. Anything that doesn't match becomes NA, which the existing
#    `filter(!is.na(victory_type))` lines downstream already handle.
.normalise_vtype <- function(v) {
    s <- trimws(as.character(v))
    titlecase <- function(x) paste0(toupper(substr(x, 1, 1)),
                                    tolower(substr(x, 2, nchar(x))))
    s <- vapply(s, titlecase, character(1), USE.NAMES = FALSE)
    s[!s %in% VICTORY_LEVELS] <- NA_character_
    factor(s, levels = VICTORY_LEVELS)
}
if ("victory_type" %in% names(game_result_df)) {
    game_result_df$victory_type <- .normalise_vtype(game_result_df$victory_type)
}
