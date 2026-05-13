package civ5

import java.io.File

import civ5.City.ProcessCitySpecializationLogs
import civ5.Civs.{AggregateCivChoices, AggregateCivPerformance}
import civ5.Economy.{AggregateCityPurchasesByEra, AggregateCivEconomyByEra, AggregateCoreYieldSourcesByEra, AggregateYieldMetrics, GetGoldBreakdownFromEconomyLogs, ProcessEconomicCityMonitorLogs, ProcessEconomicMonitorLogs, ProcessHomelandAILogs}
import civ5.Eras.{AggregateEraTransitionDeltas, ComputeErasFromResearch}
import civ5.GameResult.{AggregateAuthorityVictories, AggregateGameResultVictories, AugmentGameResultWithMapMetrics, ProcessCivGameResults, ProcessGameResultLogs}
import civ5.InstantYields.{AggregateHandicapYieldSources, AggregateInstantYieldSources, CalculateInstantYieldCumulativeSums, ProcessHandicapYieldLogs, ProcessInstantYieldLogs}
import civ5.MapState.{AggregateMapStateByEra, AggregateMapStateRecords, ProcessMapStateLogs}
import civ5.Policies.{AugmentPolicyBranchChoicesWithGameResult, ProcessPolicyChoices, ProcessPolicyLogs}
import civ5.Religion.{AggregateReligionLogs, ProcessReligionLogs}
import civ5.Technologies.ProcessTechnologyLogs
import civ5.Util.{cachedParse, listGameIds, rmTree}
import civ5.Vassalage.{ComputeVassalageMapFromDeals, ExtractVassalageDealsFromDiplomacyLogs}
import org.apache.log4j.Logger
import org.apache.spark.sql.{DataFrame, SparkSession}
import org.apache.spark.storage.StorageLevel
import org.apache.spark.{SparkConf, SparkContext}
import org.rogach.scallop.ScallopConf


class Conf(args: Seq[String]) extends ScallopConf(args) {
  mainOptions = Seq(input, output)
  val input = opt[String](descr = "input path", required = true)
  val output = opt[String](descr = "output path", required = true)
  val loadLargeTables = opt[Boolean](descr = "(deprecated, ignored)", required = false, default = Option(false))
  val resetCache = opt[Boolean](descr = "wipe parsed_cache before running", required = false, default = Option(false))
  val cacheDir = opt[String](descr = "parsed cache root", required = false, default = Option("parsed_cache"))
  val perfCsv = opt[String](descr = "perf metrics CSV path", required = false, default = Option("perf_metrics.csv"))
  verify()
}

object ProcessCiv5Logs {

  val log = Logger.getLogger(getClass.getName)

  def main(argv: Array[String]): Unit = {
    val args = new Conf(argv)

    log.info("Input: " + args.input())
    log.info("Output: " + args.output())

    val conf = new SparkConf()
      .setAppName("Civ 5 Log Processing")
      // Kryo gives much smaller serialized closures/RDD entries than Java serialization
      // — directly addresses the "task of very large size" warnings from wholeTextFiles.
      .set("spark.serializer", "org.apache.spark.serializer.KryoSerializer")
      .set("spark.kryo.registrationRequired", "false")
    val sc = new SparkContext(conf)
    val spark: SparkSession = SparkSession.builder.getOrCreate

    sc.setLogLevel("WARN")

    val inputPath = args.input()
    val cacheRoot = args.cacheDir()
    val allGameIds = listGameIds(inputPath)
    println(s"[main] discovered ${allGameIds.size} gameIds under $inputPath")

    if (args.resetCache()) {
      println(s"[main] --reset-cache: wiping $cacheRoot")
      rmTree(new File(cacheRoot))
    }

    // Derive a modpack version label from the path for perf reporting (best effort).
    val modpackVer = {
      val norm = inputPath.replace('\\', '/')
      val parts = norm.split('/').filter(_.nonEmpty)
      val idx = parts.indexOf("data")
      if (idx >= 0 && idx + 1 < parts.length) parts(idx + 1) else "unknown"
    }
    PerfTracker.configure(args.perfCsv(), modpackVer, inputPath)

    // ----- Output writer ------------------------------------------------
    // Replaces .repartition(1).write.csv(...) — single-task writes were
    // creating a hard bottleneck on the larger outputs. Coalesce based on
    // approximate row count instead.
    def dfToCSV(df: DataFrame, outLocation: String, approxRows: Long = -1L): Unit =
      PerfTracker.time(s"write_csv:$outLocation") {
        val n = if (approxRows >= 0) approxRows else df.count()
        val parts = math.max(1, math.min(64, math.ceil(n / 200000.0).toInt))
        df.coalesce(parts)
          .write
          .option("header", "true")
          .option("sep", ",")
          .mode("overwrite")
          .csv(args.output() + "/" + outLocation)
      }

    /** Persist a DF on disk-backed storage and force full materialization once. */
    def materialize(df: DataFrame, name: String, level: StorageLevel = StorageLevel.MEMORY_AND_DISK): Long = {
      df.persist(level)
      val n = df.count()
      println(s"[materialize] $name rows=$n storage=$level")
      n
    }

    // ===================================================================
    // Per-game disk cache strategy (Phase 3):
    // Each Process* call is wrapped in cachedParse, which persists parsed
    // dataframes to logs_processing/parsed_cache/<name>/ partitioned by
    // game_id. Subsequent runs only reparse log files for games not yet in
    // the cache (e.g. when a new bundle is added). Use --reset-cache to
    // invalidate when parser logic changes.
    //
    // Functions whose internal SQL joins reference views like civ_turn_era
    // must be cache-filled AFTER civ_turn_era is registered against the
    // FULL cached research data — so the join produces correct subset rows.
    // ===================================================================

    // wonders_construction: one row per wonder completion event.
    //   schema: (game_id: String, civ: String, turn: Int, wonder: String)
    //   source: */CitySpecializationLog_*.csv.gz (one per civ per game)
    val wondersDf = PerfTracker.timeDF("parse:wonders") {
      cachedParse(spark, cacheRoot, "wonders", allGameIds) { ids =>
        ProcessCitySpecializationLogs(sc, inputPath, Some(ids))
      }
    }
    wondersDf.createOrReplaceTempView("wonders_construction")
    val wondersN = materialize(wondersDf, "wonders")
    dfToCSV(wondersDf, "wonders", wondersN)

    // city_purchases: one row per city building/unit purchase.
    //   schema: (game_id, turn, civ, type ['building'|'unit'], cost: Int)
    //   source: */PlayerHomelandAILog_*.csv.gz
    val cityPurchasesDF = PerfTracker.timeDF("parse:city_purchases") {
      cachedParse(spark, cacheRoot, "city_purchases", allGameIds) { ids =>
        ProcessHomelandAILogs(sc, inputPath, Some(ids))
      }
    }
    cityPurchasesDF.createOrReplaceTempView("city_purchases")
    val cityPurchN = materialize(cityPurchasesDF, "city_purchases")
    dfToCSV(cityPurchasesDF, "city_purchases", cityPurchN)

    // game_result: one row per game indicating who won and how.
    //   schema: (game_id, turn: Int, victory_type: String, victory_civ: String)
    //   source: */*GameResult_Log.csv.gz
    val gameResultDF = PerfTracker.timeDF("parse:game_result") {
      cachedParse(spark, cacheRoot, "game_result", allGameIds) { ids =>
        ProcessGameResultLogs(sc, inputPath, Some(ids))
      }
    }
    gameResultDF.createOrReplaceTempView("game_result")
    val gameResN = materialize(gameResultDF, "game_result")
    dfToCSV(gameResultDF, "game_result", gameResN)

    // civ_game_result: per-civ end-of-game scores.
    //   schema: (game_id, civ, score: Int)
    //   source: */*GameResult_Log.csv.gz (same files, different rows)
    // civ_game_result joins game_result (already populated full) — subset cache
    // fills produce correct subset rows.
    val civGameResultDF = PerfTracker.timeDF("parse:civ_game_result") {
      cachedParse(spark, cacheRoot, "civ_game_result", allGameIds) { ids =>
        ProcessCivGameResults(sc, inputPath, Some(ids))
      }
    }
    civGameResultDF.createOrReplaceTempView("civ_game_result")
    materialize(civGameResultDF, "civ_game_result")

    // research_instance: one row per completed tech research.
    //   schema: (game_id, nation, tech, duration: Int, gridx_at_start: Int,
    //            start_turn: Int, end_turn: Int)
    //   source: */*TechAILog_*.csv.gz (one file per civ per game)
    val researchDF = PerfTracker.timeDF("parse:research") {
      cachedParse(spark, cacheRoot, "research", allGameIds) { ids =>
        ProcessTechnologyLogs(sc, inputPath, Some(ids))
      }
    }
    researchDF.createOrReplaceTempView("research_instance")
    val researchN = materialize(researchDF, "research")
    dfToCSV(researchDF, "technology_completion_records", researchN)

    // civ_turn_era: dense (game_id, civ, turn) -> era mapping, one row per
    // turn each civ exists. Derived from research_instance.
    //   schema: (game_id, civ, turn: Int, era: Int)
    //
    // civ_turn_era is derived from FULL cached research, so subsequent SQL
    // joins against it work correctly when later cache-fill steps process subsets.
    val eraDF = PerfTracker.timeDF("derive:era") { ComputeErasFromResearch(researchDF) }
    eraDF.createOrReplaceTempView("civ_turn_era")
    val eraN = materialize(eraDF, "era_transitions")
    dfToCSV(eraDF, "era_transitions", eraN)

    // city_purchases_by_era: pivoted average building/unit purchase costs per era.
    //   schema: (era: Int, avg_building_invest: Double, avg_unit_purchase: Double)
    //   inputs: city_purchases JOIN civ_turn_era
    val cityPurchasesByEraDf = PerfTracker.timeDF("agg:city_purchases_by_era") {
      AggregateCityPurchasesByEra()
    }
    val cpeN = materialize(cityPurchasesByEraDf, "city_purchases_by_era")
    dfToCSV(cityPurchasesByEraDf, "city_purchases_by_era", cpeN)

    // instant_yields: pivoted per-(game,civ,turn,reason) yield amounts. After
    // ProcessInstantYieldLogs runs, this view is replaced (in-place) with a
    // join against civ_turn_era that adds the era column.
    //   schema: (game_id, turn: Int, era: Int, civ, reason,
    //            iy_food, iy_production, iy_science, iy_gold, iy_culture,
    //            iy_faith, iy_tourism, iy_golden_age_points,
    //            iy_border_growth_points, iy_great_general_points,
    //            iy_great_admiral_points  -- all BIGINT)
    //   source: */InstantYieldSummary.csv.gz
    val instantYieldDF = PerfTracker.timeDF("parse:instant_yields") {
      cachedParse(spark, cacheRoot, "instant_yields", allGameIds) { ids =>
        ProcessInstantYieldLogs(sc, inputPath, Some(ids))
      }
    }
    instantYieldDF.createOrReplaceTempView("instant_yields")
    val iyN = materialize(instantYieldDF, "instant_yields", StorageLevel.MEMORY_AND_DISK_SER)
    dfToCSV(instantYieldDF, "instant_yields", iyN)

    // instant_yield_running_totals: cumulative-sum view of instant_yields
    // per (game_id, civ), exploded for every turn 1..500.
    //   schema: (game_id, civ, turn: Int, rt_food, rt_production, rt_gold,
    //            rt_science, rt_culture  -- all BIGINT)
    PerfTracker.time("derive:iy_running_totals") { CalculateInstantYieldCumulativeSums() }

    // gold_breakdown_by_era: era-aggregated gold income/expense breakdown.
    //   schema: (era, cities, trade_routes, city_connections, diplomacy,
    //            religion, traits, total_income, unit_maintenance,
    //            building_maintenance, improvement_maintenance,
    //            avg_building_invest, avg_unit_purchase, total_expenses
    //            -- all Double)
    //   inputs: */EconomicMonitorLog_*.csv.gz JOIN instant_yield_running_totals
    //           JOIN civ_turn_era JOIN city_purchases_by_era
    // GetGoldBreakdownFromEconomyLogs returns era-aggregated rows already; not
    // a great fit for per-game caching, so leave uncached.
    val goldBreakdownDf = PerfTracker.timeDF("agg:gold_breakdown") {
      GetGoldBreakdownFromEconomyLogs(sc, inputPath)
    }
    val gbdN = materialize(goldBreakdownDf, "gold_breakdown")
    dfToCSV(goldBreakdownDf, "gold_breakdown_by_era", gbdN)

    // era_transition_deltas: turn each civ first reached each era.
    //   schema: (game_id, civ, transition_turn: Int, era: Int)
    //   inputs: civ_turn_era
    val eraTransitionDeltasDF = PerfTracker.timeDF("agg:era_transition_deltas") {
      AggregateEraTransitionDeltas()
    }
    val etdN = materialize(eraTransitionDeltasDF, "era_transition_deltas")
    dfToCSV(eraTransitionDeltasDF, "era_transition_deltas", etdN)

    // (Removed: redundant second ProcessGameResultLogs call from the original main.)

    // religion_choices: one row per religion belief picked by each civ.
    //   schema: shape from ProcessReligionLogs (game_id, turn, civ, belief, ...)
    //   source: */ReligionLog.csv.gz
    val religionChoicesDF = PerfTracker.timeDF("parse:religion_choices") {
      cachedParse(spark, cacheRoot, "religion_choices", allGameIds) { ids =>
        ProcessReligionLogs(sc, inputPath, Some(ids))
      }
    }
    religionChoicesDF.createOrReplaceTempView("religion_choices")
    val relChoiceN = materialize(religionChoicesDF, "religion_choices")
    dfToCSV(religionChoicesDF, "religion_choices", relChoiceN)

    // religion_stats: aggregated counts/win-rates per belief across games.
    //   inputs: religion_choices JOIN civ_game_result
    val religionStatsDF = PerfTracker.timeDF("agg:religion_stats") { AggregateReligionLogs() }
    val relStatsN = materialize(religionStatsDF, "religion_stats")
    dfToCSV(religionStatsDF, "religion_stats", relStatsN)

    // branch_choice_stats: policy branch openings.
    //   schema: (game_id, turn: Int, civ, branch)
    //   source: */PolicyAILog_*.csv.gz
    val branchChoiceDF = PerfTracker.timeDF("parse:branch_choices") {
      cachedParse(spark, cacheRoot, "branch_choices", allGameIds) { ids =>
        ProcessPolicyLogs(sc, inputPath, Some(ids))
      }
    }
    branchChoiceDF.createOrReplaceTempView("branch_choice_stats")
    val branchChN = materialize(branchChoiceDF, "branch_choices")
    dfToCSV(branchChoiceDF, "branch_choices", branchChN)

    // policy_choices: individual policy/tenet picks.
    //   schema: (game_id, turn: Int, civ, item)
    //   source: */PolicyAILog_*.csv.gz
    val policyChoiceDF = PerfTracker.timeDF("parse:policy_choices") {
      cachedParse(spark, cacheRoot, "policy_choices", allGameIds) { ids =>
        ProcessPolicyChoices(sc, inputPath, Some(ids))
      }
    }
    policyChoiceDF.createOrReplaceTempView("policy_choices")
    val polChoiceN = materialize(policyChoiceDF, "policy_choices")
    dfToCSV(policyChoiceDF, "policy_choices", polChoiceN)

    // branch_stats: branch_choice_stats joined with civ_game_result for
    // win-rate analysis per policy branch.
    val branchStatsDF = PerfTracker.timeDF("agg:branch_stats") {
      AugmentPolicyBranchChoicesWithGameResult()
    }
    val branchSN = materialize(branchStatsDF, "branch_stats")
    dfToCSV(branchStatsDF, "branch_stats", branchSN)

    // civ_choices: per-(game_id, civ) summary of branch + religion picks,
    // one row per civ per game.
    val civChoicesDF = PerfTracker.timeDF("agg:civ_choices") {
      AggregateCivChoices(branchChoiceDF, religionChoicesDF)
    }
    val civChN = materialize(civChoicesDF, "civ_choices")
    dfToCSV(civChoicesDF, "civ_choices", civChN)

    // vassalage_deal: one row per vassal/master diplomatic agreement.
    //   schema: (game_id, turn: Int, vassal: String, master: String)
    //   source: */DiplomacyAI_TradeAgreements_Log_.csv.gz
    val vassalageDF = PerfTracker.timeDF("parse:vassalage") {
      cachedParse(spark, cacheRoot, "vassalage", allGameIds) { ids =>
        ExtractVassalageDealsFromDiplomacyLogs(sc, inputPath, Some(ids))
      }
    }
    vassalageDF.createOrReplaceTempView("vassalage_deal")
    val vassalageN = materialize(vassalageDF, "vassalage")
    dfToCSV(vassalageDF, "vassalage", vassalageN)

    // vassalage_map: registers a (game_id, turn, civ -> master) lookup view
    // and returns a DataFrame of the latest vassal/master relationships per
    // game alongside the in-memory stripes map used by power_ranking later.
    val (vassalageMapDF, _) = PerfTracker.time("derive:vassalage_map") { ComputeVassalageMapFromDeals() }
    val vassalageMapN = materialize(vassalageMapDF, "vassalage_map")
    dfToCSV(vassalageMapDF, "vassalage_map", vassalageMapN)

    // map_state: one row per tile per turn snapshot. This is the largest
    // intermediate by far (~10M rows on a 6-game sample).
    //   schema: (game_id, owner_civ, turn: String, city_id: Int,
    //            route_type: Int, unit, unit_owner_civ, x: Int, y: Int)
    //   source: */mapStateLog_Turn*.json.gz
    val mapStateDF = PerfTracker.timeDF("parse:map_state") {
      cachedParse(spark, cacheRoot, "map_state", allGameIds) { ids =>
        ProcessMapStateLogs(sc, inputPath, Some(ids))
      }
    }
    mapStateDF.createOrReplaceTempView("map_state")
    materialize(mapStateDF, "map_state", StorageLevel.MEMORY_AND_DISK_SER)

    // map_state_records: registers aggregated per-(game,civ,turn) tile/city
    // counts as a temp view; no DataFrame returned.
    PerfTracker.time("agg:map_state_records") { AggregateMapStateRecords(mapStateDF) }

    // map_state_by_era: per-(game, civ, era) average tiles/cities owned.
    //   schema: (game_id, civ, era: Int, tiles_owned: Double, cities_owned: Double)
    val mapStateByEraDF = PerfTracker.timeDF("agg:map_state_by_era") {
      AggregateMapStateByEra(mapStateDF)
    }
    val mseN = materialize(mapStateByEraDF, "map_state_by_era")
    dfToCSV(mapStateByEraDF, "map_state_by_era", mseN)

    // We can drop the raw mapStateDF cache once map_state_by_era is materialized,
    // freeing storage for the rest of the pipeline.
    mapStateDF.unpersist(blocking = false)

    // handicap_yields: pivoted per-(game,civ,turn,reason) handicap bonus yields.
    //   schema: (game_id, civ, turn: Int, reason,
    //            hy_gold, hy_food, hy_culture, hy_science -- all numeric)
    //   source: */DifficultyHandicapLog.csv.gz
    val handicapYieldsDF = PerfTracker.timeDF("parse:handicap_yields") {
      cachedParse(spark, cacheRoot, "handicap_yields", allGameIds) { ids =>
        ProcessHandicapYieldLogs(sc, inputPath, Some(ids))
      }
    }
    handicapYieldsDF.createOrReplaceTempView("handicap_yields")
    val hyN = materialize(handicapYieldsDF, "handicap_yields")
    dfToCSV(handicapYieldsDF, "handicap_yields", hyN)

    // city_economy: per-city, per-turn economic snapshot.
    //   schema: (game_id, civ, turn: Int, city_name, population, food,
    //            production, gold, science, ...) -- ~30 numeric columns
    //   source: */EconomicCityMonitorLog_*.csv.gz
    val cityEconomyDF = PerfTracker.timeDF("parse:city_economy") {
      cachedParse(spark, cacheRoot, "city_economy", allGameIds) { ids =>
        ProcessEconomicCityMonitorLogs(sc, inputPath, Some(ids))
      }
    }
    cityEconomyDF.createOrReplaceTempView("city_economy")
    val ceN = materialize(cityEconomyDF, "city_economy", StorageLevel.MEMORY_AND_DISK_SER)
    dfToCSV(cityEconomyDF, "city_economy", ceN)

    // civ_economy: per-civ, per-turn economic snapshot (city-rolled-up).
    //   schema: (game_id, civ, turn: Int, city_count, population, food,
    //            production, science, city_gold, ...) -- ~30 numeric columns
    //   source: */EconomicMonitorLog_*.csv.gz
    val civEconomyDF = PerfTracker.timeDF("parse:civ_economy") {
      cachedParse(spark, cacheRoot, "civ_economy", allGameIds) { ids =>
        ProcessEconomicMonitorLogs(sc, inputPath, Some(ids))
      }
    }
    civEconomyDF.createOrReplaceTempView("civ_economy")
    materialize(civEconomyDF, "civ_economy", StorageLevel.MEMORY_AND_DISK_SER)

    // instant_yield_sources: Map[yieldType -> DataFrame], one DF per yield
    // (food, production, gold, science, culture). Each DF has columns
    // (era, reason, avg_amount: Double) -- a per-era breakdown of where
    // each yield came from. Written one CSV per yield type.
    val instantYieldSources = PerfTracker.time("agg:instant_yield_sources") {
      AggregateInstantYieldSources()
    }
    instantYieldSources.foreach { case (yieldType, yieldDF) =>
      dfToCSV(yieldDF, s"${yieldType}_instant_yield_sources")
    }

    // handicap_yield_sources: Map[yieldType -> DataFrame] (food/gold/science
    // /culture). Same shape as instant_yield_sources but for handicap yields.
    val handicapYieldSources = PerfTracker.time("agg:handicap_yield_sources") {
      AggregateHandicapYieldSources()
    }
    handicapYieldSources.foreach { case (yieldType, yieldDF) =>
      dfToCSV(yieldDF, s"${yieldType}_handicap_yield_sources")
    }

    // yields_summary_by_turn: per-(game, civ, turn) totals across yield
    // sources (instant + handicap + economy), used for cross-source comparison.
    val yieldsSourcesByTurnDF = PerfTracker.timeDF("agg:yield_sources_by_turn") {
      AggregateYieldMetrics()
    }
    val ysbtN = materialize(yieldsSourcesByTurnDF, "yields_summary_by_turn", StorageLevel.MEMORY_AND_DISK_SER)
    dfToCSV(yieldsSourcesByTurnDF, "yield_sources_by_turn", ysbtN)

    // civ_economy_by_era: per-(game, civ, era) averaged civ_economy columns.
    val civEconomyByEraDF = PerfTracker.timeDF("agg:civ_economy_by_era") {
      AggregateCivEconomyByEra()
    }
    val ceeN = materialize(civEconomyByEraDF, "civ_economy_by_era", StorageLevel.MEMORY_AND_DISK_SER)
    dfToCSV(civEconomyByEraDF, "civ_economy_by_era", ceeN)

    // yield_sources_by_era: per-era averaged contributions of each yield
    // source for the 5 core yields (food/production/gold/science/culture).
    val yieldsSourcesByEraDF = PerfTracker.timeDF("agg:yield_sources_by_era") {
      AggregateCoreYieldSourcesByEra()
    }
    val ysbeN = materialize(yieldsSourcesByEraDF, "yield_sources_by_era", StorageLevel.MEMORY_AND_DISK_SER)
    dfToCSV(yieldsSourcesByEraDF, "yield_sources_by_era", ysbeN)

    // vic_frequency: count of games per victory_type.
    //   schema: (victory_type: String, n: Long)
    val victoryTypeSummaryDF = PerfTracker.timeDF("agg:vic_frequency") {
      AggregateGameResultVictories()
    }
    val vfN = materialize(victoryTypeSummaryDF, "vic_frequency")
    dfToCSV(victoryTypeSummaryDF, "vic_frequency", vfN)

    // augmented_game_result: registers game_result enriched with map_state
    // metrics (final tile/city counts) as a temp view; no DataFrame returned.
    PerfTracker.time("derive:augmented_game_result") { AugmentGameResultWithMapMetrics() }

    // power_ranking: per-(game, civ) end-of-game performance metrics, with
    // final score, tiles, cities, and victory placement.
    val civPowerRankingDF = PerfTracker.timeDF("agg:power_ranking") { AggregateCivPerformance() }
    val prN = materialize(civPowerRankingDF, "power_ranking")
    dfToCSV(civPowerRankingDF, "power_ranking", prN)

    // authority_victories: count of games where an Authority-branch civ won.
    //   schema: (victory_type, n: Long)
    val authorityVictoryDf = PerfTracker.timeDF("agg:authority_victories") {
      AggregateAuthorityVictories()
    }
    val avN = materialize(authorityVictoryDf, "authority_victories")
    dfToCSV(authorityVictoryDf, "authority_victories", avN)

    println("[main] all steps complete; perf metrics appended to " + args.perfCsv())
  }
}
