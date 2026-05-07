# Check power_ranking_df data

source("r_scripts/common.R")

wonders_df <- load_spark_csv("wonders")
games_per_civ <- power_ranking_df %>%
    transmute(civ, count_games = as.numeric(count_games)) %>%
    filter(count_games > 0) %>%
    arrange(desc(count_games))

cat("=== POWER RANKING - Games per Civ ===\n\n")

# Show top 30
cat("TOP 30 CIVS by games participated:\n")
print(head(games_per_civ, 30))

cat("\n\nCIVS WITH COUNT_GAMES = 1:\n")
one_game_civs <- games_per_civ %>% filter(count_games == 1)
print(one_game_civs)

cat("\n\nTotal unique civs in power_ranking_df:", n_distinct(power_ranking_df$civ), "\n")
cat("Total unique games:", n_distinct(wonders_df$game_id), "\n")

# Check how many games each civ appears in wonders_df
actual_games_per_civ <- wonders_df %>%
    group_by(civ) %>%
    summarise(actual_games = n_distinct(game_id), .groups = "drop") %>%
    arrange(desc(actual_games))

cat("\n\nACTUAL GAMES PER CIV (from wonders data):\n")
print(head(actual_games_per_civ, 30))

# Compare - find discrepancies
comparison <- games_per_civ %>%
    rename(reported_games = count_games) %>%
    left_join(actual_games_per_civ, by = "civ") %>%
    mutate(discrepancy = actual_games - reported_games) %>%
    filter(discrepancy > 0) %>%
    arrange(desc(discrepancy))

cat("\n\nCIVS WITH DISCREPANCIES (actual > reported):\n")
print(head(comparison, 30))
