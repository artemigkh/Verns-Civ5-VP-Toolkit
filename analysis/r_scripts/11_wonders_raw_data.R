# 11_wonders_raw_data.R -- Export raw wonders data for debugging.
# Shows all wonders constructed by game by civ, with detailed breakdown.
# Outputs to: analysis/output/wonders_raw_data.txt

source("r_scripts/common.R")

wonders_df <- load_spark_csv("wonders")

# Load the wonder era filter to understand what's considered a "real" wonder
wonder_name_filter <- read_csv("../db_util/out/wonder_eras.csv", show_col_types = FALSE)$Name

# Get unique games and sort them
all_games <- unique(wonders_df$game_id)
n_games <- length(all_games)

# Output file
output_file <- "output/wonders_raw_data.txt"

sink(output_file)

cat("=============================================================================\n")
cat("RAW WONDERS DATA: All wonders by game and civ\n")
cat("=============================================================================\n")
cat(sprintf("Total unique games: %d\n", n_games))
cat(sprintf("Total wonder records: %d\n", nrow(wonders_df)))
cat("\n")

# Process each game (show all games, but highlight first 10)
for (i in seq_along(all_games)) {
    game <- all_games[[i]]
    game_data <- wonders_df %>%
        filter(game_id == game) %>%
        arrange(civ, turn)
    
    if (i <= 10 || i == n_games) {  # Show first 10 + last game for context
        cat(sprintf("\n%s GAME %d: %s\n", 
                    ifelse(i <= 10, "---", "***"),
                    i, game))
        cat(sprintf("   Total wonders in game: %d\n", nrow(game_data)))
        
        # Count by civ
        by_civ <- game_data %>%
            group_by(civ) %>%
            summarise(count = n(), .groups = "drop") %>%
            arrange(desc(count))
        
        cat("   By civilization:\n")
        for (j in seq_len(nrow(by_civ))) {
            row <- by_civ[j, ]
            cat(sprintf("      %s: %d wonders\n", row$civ, row$count))
        }
        
        cat("   Detailed list:\n")
        for (j in seq_len(nrow(game_data))) {
            row <- game_data[j, ]
            is_real_wonder <- row$wonder %in% wonder_name_filter
            marker <- ifelse(is_real_wonder, "  ", "X ")
            cat(sprintf("      %s Turn %3d | %s | %s\n",
                       marker, row$turn, row$civ, row$wonder))
        }
    } else if (i == 11) {
        cat("\n... (showing summary for games 11-last) ...\n")
    }
    
    # Always output summary line for all games
    if (i > 10 && i < n_games) {
        if (i == 11) {
            # Print header for summary section
            cat("\nGAME | TOTAL WONDERS | TOP CIV | TOP CIV COUNT | REAL WONDERS\n")
        }
        by_civ_summary <- game_data %>%
            group_by(civ) %>%
            summarise(count = n(), .groups = "drop") %>%
            arrange(desc(count))
        
        real_count <- sum(game_data$wonder %in% wonder_name_filter)
        top_civ_count <- by_civ_summary$count[1]
        top_civ <- by_civ_summary$civ[1]
        
        cat(sprintf("%3d  | %13d | %s | %13d | %d\n",
                   i, nrow(game_data), top_civ, top_civ_count, real_count))
    }
}

# Summary statistics
cat("\n\n=============================================================================\n")
cat("SUMMARY STATISTICS\n")
cat("=============================================================================\n")

# Wonders filtered vs unfiltered
filtered_count <- sum(wonders_df$wonder %in% wonder_name_filter)
unfiltered_count <- nrow(wonders_df)
duplicate_count <- unfiltered_count - filtered_count

cat(sprintf("Total wonders (unfiltered): %d\n", unfiltered_count))
cat(sprintf("Total wonders (filtered by wonder_eras.csv): %d\n", filtered_count))
cat(sprintf("Non-wonder entries (filtered out): %d\n", duplicate_count))
cat(sprintf("Filter effectiveness: %.1f%% removed\n", 
            100 * duplicate_count / unfiltered_count))

# Top non-wonder entries
cat("\nTop entries filtered out (not in wonder_eras.csv):\n")
non_wonders <- wonders_df %>%
    filter(!(wonder %in% wonder_name_filter)) %>%
    group_by(wonder) %>%
    summarise(count = n(), .groups = "drop") %>%
    arrange(desc(count)) %>%
    head(15)

for (i in seq_len(nrow(non_wonders))) {
    row <- non_wonders[i, ]
    cat(sprintf("   %s: %d entries\n", row$wonder, row$count))
}

cat("\nTop wonders (actual wonders):\n")
real_wonders <- wonders_df %>%
    filter(wonder %in% wonder_name_filter) %>%
    group_by(wonder) %>%
    summarise(count = n(), .groups = "drop") %>%
    arrange(desc(count)) %>%
    head(15)

for (i in seq_len(nrow(real_wonders))) {
    row <- real_wonders[i, ]
    cat(sprintf("   %s: %d times\n", row$wonder, row$count))
}

# Top civs by total wonders (unfiltered)
cat("\nTop civilizations by total wonders built (unfiltered):\n")
top_civs <- wonders_df %>%
    group_by(civ) %>%
    summarise(total = n(), .groups = "drop") %>%
    arrange(desc(total)) %>%
    head(10)

for (i in seq_len(nrow(top_civs))) {
    row <- top_civs[i, ]
    cat(sprintf("   %s: %d\n", row$civ, row$total))
}

sink()

cat("Output saved to:", output_file, "\n")
