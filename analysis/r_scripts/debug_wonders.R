# Debug script: Compare filtered vs unfiltered wonders averages

source("r_scripts/common.R")

wonders_df_raw <- load_spark_csv("wonders")
wonder_name_filter <- read_csv("../db_util/out/wonder_eras.csv", show_col_types = FALSE)$Name
wonders_df_filtered <- wonders_df_raw %>% filter(wonder %in% wonder_name_filter)

cat("=== WONDER FILTER ANALYSIS ===\n\n")
cat("Total wonders (unfiltered):", nrow(wonders_df_raw), "\n")
cat("Total wonders (filtered):", nrow(wonders_df_filtered), "\n")
cat("Valid wonder names in filter:", length(wonder_name_filter), "\n\n")

# Compare unfiltered vs filtered per civ
unfiltered_per_civ <- wonders_df_raw %>%
    group_by(civ) %>%
    summarise(total_unfiltered = n(), .groups = "drop") %>%
    arrange(desc(total_unfiltered))

filtered_per_civ <- wonders_df_filtered %>%
    group_by(civ) %>%
    summarise(total_filtered = n(), .groups = "drop") %>%
    arrange(desc(total_filtered))

# Get games per civ
games_per_civ <- power_ranking_df %>%
    transmute(civ, count_games = as.numeric(count_games)) %>%
    filter(count_games > 0)

# Join and compare
comparison <- unfiltered_per_civ %>%
    left_join(filtered_per_civ, by = "civ") %>%
    left_join(games_per_civ, by = "civ") %>%
    mutate(
        avg_unfiltered = total_unfiltered / count_games,
        avg_filtered = total_filtered / count_games
    ) %>%
    arrange(desc(avg_unfiltered))

cat("TOP 20 CIVS - COMPARING UNFILTERED VS FILTERED AVERAGES:\n")
cat("Civ | Games | Unfiltered Total | Filtered Total | Avg Unfiltered | Avg Filtered\n")
cat("----+-------+------------------+----------------+----------------+-------------\n")

for (i in seq_len(min(20, nrow(comparison)))) {
    row <- comparison[i, ]
    cat(sprintf("%s | %5d | %16d | %14d | %14.2f | %12.2f\n",
               row$civ, row$count_games, row$total_unfiltered, 
               row$total_filtered, row$avg_unfiltered, row$avg_filtered))
}

cat("\n\nMAX AVERAGE UNFILTERED:", max(comparison$avg_unfiltered, na.rm = TRUE), "\n")
cat("MAX AVERAGE FILTERED:", max(comparison$avg_filtered, na.rm = TRUE), "\n")

# Show the actual data for the worst offender
worst <- comparison %>% filter(avg_unfiltered == max(avg_unfiltered, na.rm = TRUE)) %>% pull(civ)
cat("\n\nTop civ by average unfiltered wonders per game:", worst, "\n")

worst_data <- comparison %>% filter(civ == worst)
print(worst_data)
