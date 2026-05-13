# make_composites.R -- compose existing r_plots into compound visualizations.
#
# Reads finished PNGs from analysis/output/r_plots/dark/ (and its subdirs)
# and writes composite images to analysis/output/r_plots/dark/composites/.
# Uses {magick} for image-level composition (no ggplot here).
#
# Each composite stacks caption-less ("_nocap") versions of its inputs
# and appends a single bottom-right info caption to the final image, so
# the per-input captions don't double up in the middle of the figure.
#
# Run with CWD == analysis/, e.g.:
#   Rscript r_scripts/make_composites.R

source("r_scripts/common.R")
suppressPackageStartupMessages(library(magick))

DARK_DIR <- file.path("output", "r_plots", "dark")
OUT_DIR  <- file.path(DARK_DIR, "composites")
dir.create(OUT_DIR, recursive = TRUE, showWarnings = FALSE)

BG <- IPSUM_VP_DARK_BG  # matches the underlying dark plots.

# Caption styling matches the per-plot dark captions (grey60, italic).
CAPTION_COLOR  <- "grey60"
CAPTION_SIZE   <- 18L
CAPTION_HEIGHT <- 100L
CAPTION_TEXT   <- default_caption()

# -----------------------------------------------------------------------------
# Helpers.
# -----------------------------------------------------------------------------

read_img <- function(path) {
    if (!file.exists(path)) {
        stop("Missing image: ", path)
    }
    image_read(path)
}

# Scale every image in `imgs` to the same width (the max width by default),
# preserving aspect ratio; then stack vertically.
stack_v <- function(imgs, target_width = NULL) {
    info  <- image_info(imgs)
    if (is.null(target_width)) target_width <- max(info$width)
    scaled <- lapply(seq_along(imgs), function(i) {
        image_scale(imgs[i], paste0(target_width, "x"))
    })
    image_append(do.call(c, scaled), stack = TRUE)
}

# Scale every image in `imgs` to the same height (the max height by default),
# preserving aspect ratio; then concat horizontally.
stack_h <- function(imgs, target_height = NULL) {
    info  <- image_info(imgs)
    if (is.null(target_height)) target_height <- max(info$height)
    scaled <- lapply(seq_along(imgs), function(i) {
        image_scale(imgs[i], paste0("x", target_height))
    })
    image_append(do.call(c, scaled), stack = FALSE)
}

# Pad the bottom with a strip of bg-colored canvas and annotate the
# single bottom-right info caption.
add_caption_strip <- function(img) {
    info <- image_info(img)
    canvas <- image_blank(width  = info$width,
                          height = info$height + CAPTION_HEIGHT,
                          color  = BG)
    out <- image_composite(canvas, img, offset = "+0+0")
    image_annotate(out, CAPTION_TEXT,
                   gravity  = "southeast",
                   location = "+24+10",
                   size     = CAPTION_SIZE,
                   color    = CAPTION_COLOR,
                   style    = "italic")
}

save_composite <- function(img, name) {
    img <- add_caption_strip(img)
    out <- file.path(OUT_DIR, paste0(name, ".png"))
    image_write(img, out, format = "png")
    cat("saved:", out, "\n")
    invisible(out)
}

p <- function(name) file.path(DARK_DIR, name)

# -----------------------------------------------------------------------------
# 1. Victory Types: top = 01b, bottom = 02b
# -----------------------------------------------------------------------------
{
    imgs <- c(read_img(p("01b_donut_violin_bees_nocap.png")),
              read_img(p("02b_winrate_by_civ_stacked_bars_nocap.png")))
    save_composite(stack_v(imgs), "victory_types")
}

# -----------------------------------------------------------------------------
# 2. Augmented Victory Types: top = 03b, bottom = 04b
# -----------------------------------------------------------------------------
{
    imgs <- c(read_img(p("03b_pseudo_dom_victory_mix_nocap.png")),
              read_img(p("04b_pseudo_dom_winrate_by_civ_nocap.png")))
    save_composite(stack_v(imgs), "augmented_victory_types")
}

# -----------------------------------------------------------------------------
# 3. Religious Attainment: top = 05b, bottom = 10f
# -----------------------------------------------------------------------------
{
    imgs <- c(read_img(p("05b_religion_attainment_times_nocap.png")),
              read_img(p("10f_religion_sankey_aligned_nocap.png")))
    save_composite(stack_v(imgs), "religious_attainment")
}

# -----------------------------------------------------------------------------
# 4. Policies: left = 15b (full height), right column = three stacked
#     panels: policy_flow/_all_civs, 16b, 16d.
# -----------------------------------------------------------------------------
{
    left  <- read_img(p("15b_policy_branch_table_nocap.png"))
    right_imgs <- c(
        read_img(p("policy_flow/_all_civs_nocap.png")),
        read_img(p("16b_policy_branch_wins_bars_nocap.png")),
        read_img(p("16d_policy_branch_winrate_bars_nocap.png"))
    )
    right <- stack_v(right_imgs)
    # Now align the heights: scale `left` and `right` to the max height
    # between them, preserving aspect ratios, then concat horizontally.
    save_composite(stack_h(c(left, right)), "policies")
}

# -----------------------------------------------------------------------------
# 5. Science: left = 11b, right = 12b
# -----------------------------------------------------------------------------
{
    imgs <- c(read_img(p("11b_tech_research_time_by_era_ridgeline_nocap.png")),
              read_img(p("12b_era_progression_time_violin_nocap.png")))
    save_composite(stack_h(imgs), "science")
}

cat("\nAll composites written to:", normalizePath(OUT_DIR, mustWork = FALSE), "\n")
