# Verify the fix produces reasonable averages

source("r_scripts/common.R")

wonders_df <- load_spark_csv("wonders")
wonders_df <- synth_clone_per_game(wonders_df, "wonders_df")

# Restrict to wonders listed in wonder_eras.csv
wonder_name_filter <- read_csv("../db_util/out/wonder_eras.csv", show_col_types = FALSE)$Name
wonders_df <- wonders_df %>% filter(wonder %in% wonder_name_filter)

# Wonders built per civ
wonders_per_civ <- wonders_df %>%
    group_by(civ) %>%
    summarise(total_wonders = n(), .groups = "drop")

# Games each civ participated in (CORRECTED: from wonders_df, not power_ranking_df)
games_per_civ <- wonders_df %>%
    group_by(civ) %>%
    summarise(count_games = n_distinct(game_id), .groups = "drop")

avg_wonders_df <- wonders_per_civ %>%
    inner_join(games_per_civ, by = "civ") %>%
    mutate(avg_wonders = total_wonders / count_games) %>%
    arrange(desc(avg_wonders))

cat("=== CORRECTED AVERAGES ===\n")
cat("Top 20 civs by average wonders per game:\n")
print(head(avg_wonders_df, 20))

cat("\n\nStatistics:\n")
cat("Max average:", max(avg_wonders_df$avg_wonders), "\n")
cat("Min average:", min(avg_wonders_df$avg_wonders), "\n")
cat("Mean average:", mean(avg_wonders_df$avg_wonders), "\n")
cat("Median average:", median(avg_wonders_df$avg_wonders), "\n")
