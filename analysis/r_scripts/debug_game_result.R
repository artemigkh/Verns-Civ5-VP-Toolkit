# Check game_result_df for actual game participation

source("r_scripts/common.R")

game_result_df_check <- load_spark_csv("game_result")
wonders_df_raw <- load_spark_csv("wonders")

cat("Games in game_result_df:", n_distinct(game_result_df_check$game_id), "\n")
cat("Games in wonders_df:", n_distinct(wonders_df_raw$game_id), "\n")
cat("Civs in game_result_df:", n_distinct(game_result_df_check$civ), "\n")
cat("Civs in wonders_df:", n_distinct(wonders_df_raw$civ), "\n\n")

# Get actual game participation from game_result
actual_games_from_result <- game_result_df_check %>%
    group_by(civ) %>%
    summarise(actual_games = n_distinct(game_id), .groups = "drop") %>%
    arrange(desc(actual_games))

cat("TOP CIVS by actual games (from game_result):\n")
print(head(actual_games_from_result, 20))
