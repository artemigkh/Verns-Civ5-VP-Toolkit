package civ5

import SparkJob.spark.implicits._
import civ5.Util.{getGameIdLogContentsRDD, parseLogFile}
import org.apache.spark.SparkContext
import org.apache.spark.sql.DataFrame
object Economy extends SparkJob {
  /**
   * Processes EconomicCityMonitorLog_*.csv files and returns a dataframe of per-city economy metrics,
   * one row per game_id, civ, city, turn
   *
   * Additionally, registers the dataframe under the Spark SQL temporary view "city_economy"
   *
   * @param sc        - the spark context object
   * @param inputPath - base path of the logs
   * @return Spark Dataframe containing processed log rows
   */
  def ProcessEconomicCityMonitorLogs(
      sc: SparkContext,
      inputPath: String,
      gameIds: Option[Set[String]] = None
  ): DataFrame = {
    val cityEconomyDF = getGameIdLogContentsRDD(sc, inputPath, "/*/EconomicCityMonitorLog_*.csv", gameIds)
      .flatMap {
        case (gameId, logFile) =>
          parseLogFile(gameId, "/*/EconomicCityMonitorLog_*.csv") {
            logFile.split('\n')
              // Drop header rows (defensive — older VP versions emit data-only,
              // newer ones may include a header that we must skip before
              // index-based parsing).
              .filterNot(s => s.contains("Turn,"))
              // Drop blank lines. "".split(',') returns Array("") of length
              // 1, which would crash the index-based extraction below for
              // gameIds whose civ never recorded any economy data (the bundle
              // still ships an empty EconomicCityMonitorLog_<civ>.csv.gz).
              .filter(_.trim.nonEmpty)
              // Extract columns of interest
              .map(line => {
                val lineArr = line.split(',').map(s => s.trim)
                (
                  gameId,
                  lineArr(0), // civ
                  lineArr(1).toInt, // turn
                  lineArr(2), // city_name
                  lineArr(3).toDouble, // population
                  lineArr(4).toDouble, // food
                  lineArr(5).toDouble, // production
                  lineArr(6).toDouble, // science
                  lineArr(7).toDouble, // gold
                  lineArr(8).toDouble, // culture
                  lineArr(9).toDouble, // faith
                  lineArr(10).toDouble, // tourism
                  lineArr(11).toDouble // golden_age_points
                )
              })
          }
      }
      .toDF("game_id", "civ", "turn", "city_name", "population", "food", "production", "gold", "science",
        "culture", "faith", "tourism", "golden_age_points")
    cityEconomyDF.createOrReplaceTempView("city_economy")

    val cityEconomyWithEraDF = spark.sql(
      """
        | SELECT
        |   ce.game_id,
        |   ce.civ,
        |   ce.turn,
        |   era,
        |   city_name,
        |   population,
        |   food,
        |   production,
        |   gold,
        |   science,
        |   culture,
        |   faith,
        |   tourism,
        |   golden_age_points
        | FROM city_economy ce, civ_turn_era e
        | WHERE
        |   ce.game_id = e.game_id AND
        |   ce.civ = e.civ AND
        |   ce.turn = e.turn
        |""".stripMargin)
    cityEconomyWithEraDF
  }

  /**
   * Processes EconomicMonitorLog_*.csv files and returns a dataframe of per-civ economy metrics,
   * one row per game_id, civ, turn
   *
   * Additionally, registers the dataframe under the Spark SQL temporary view "civ_economy"
   *
   * @param sc        - the spark context object
   * @param inputPath - base path of the logs
   * @return Spark Dataframe containing processed log rows
   */
  def ProcessEconomicMonitorLogs(
      sc: SparkContext,
      inputPath: String,
      gameIds: Option[Set[String]] = None
  ): DataFrame = {
    getGameIdLogContentsRDD(sc, inputPath, "/*/EconomicMonitorLog_*.csv", gameIds)
      .flatMap {
        case (gameId, logFile) =>
          parseLogFile(gameId, "/*/EconomicMonitorLog_*.csv") {
            logFile.split('\n')
              // Drop header rows
              .filterNot(s => s.contains("Turn,"))
              // Drop blank lines (see ProcessEconomicCityMonitorLogs).
              .filter(_.trim.nonEmpty)
              // Extract columns of interest
              .map(line => {
                val lineArr = line.split(',').map(s => s.trim)

                (
                  gameId,
                  lineArr(0), // civ
                  lineArr(1).toInt, // turn
                  lineArr(2).toDouble.toInt, // city_count
                  lineArr(3).toDouble.toInt, // population
                  lineArr(4).toDouble.toInt, // food
                  lineArr(5).toDouble.toInt, // production
                  lineArr(7).toDouble.toInt, // science
                  lineArr(25).toDouble.toInt, // gold from cities (no tr)
                  lineArr(8).toDouble.toInt, // culture
                  lineArr(9).toDouble.toInt, // faith
                  lineArr(10).toDouble.toInt,// tourism
                  lineArr(11).toDouble.toInt, // golden_age_points
                  lineArr(13).toDouble.toInt, // policies_acquired
                  lineArr(14).toDouble.toInt, // culture_cumsum
                  lineArr(16).toDouble.toInt, // workers
                  lineArr(19).toDouble.toInt, // happiness
                  lineArr(23).toDouble.toInt, // trade_units_active
                  lineArr(33).toDouble.toInt, // unit_maintenance
                  lineArr(34).toDouble.toInt, // building_maintenance
                  lineArr(35).toDouble.toInt, // improvement_maintenance
                  lineArr(32).toDouble.toInt // total_income (gold)
                )
              })
          }
      }
      .toDF("game_id", "civ", "turn", "city_count", "population", "food", "production", "science", "city_gold",
        "culture", "faith", "tourism", "golden_age_points", "policies_acquired", "culture_cumsum",
        "workers", "happiness", "trade_units_active", "unit_maintenance", "building_maintenance",
        "improvement_maintenance", "gold")
      .createOrReplaceTempView("civ_economy")

    val civEconomyDF = spark.sql(
      """
        | SELECT
        |   ce.game_id,
        |   ce.civ,
        |   ce.turn,
        |   era,
        |   ce.city_count,
        |   ce.population,
        |   ce.policies_acquired,
        |   ce.workers,
        |   ce.happiness,
        |   ce.trade_units_active,
        |   ce.unit_maintenance,
        |   ce.building_maintenance,
        |   ce.improvement_maintenance,
        |   ce.food - (rt_food / (rt.turn + 1)) AS food,
        |   ce.production - (rt_production / (rt.turn + 1)) AS production,
        |   ce.gold - (rt_gold / (rt.turn + 1)) AS gold,
        |   ce.science - (rt_science / (rt.turn + 1)) AS science,
        |   ce.culture - (rt_culture / (rt.turn + 1)) AS culture,
        |   ce.city_gold,
        |   ce.faith,
        |   ce.tourism,
        |   ce.golden_age_points
        | FROM
        |   civ_economy ce, instant_yield_running_totals rt, civ_turn_era e
        | WHERE
        |   ce.game_id = rt.game_id AND
        |   ce.civ = rt.civ AND
        |   ce.turn = rt.turn AND
        |   ce.game_id = e.game_id AND
        |   ce.civ = e.civ AND
        |   ce.turn = e.turn
        |""".stripMargin)
    civEconomyDF.createOrReplaceTempView("civ_economy")
    civEconomyDF
  }

  def GetGoldBreakdownFromEconomyLogs(
      sc: SparkContext,
      inputPath: String,
      gameIds: Option[Set[String]] = None
  ): DataFrame = {
    getGameIdLogContentsRDD(sc, inputPath, "/*/EconomicMonitorLog_*.csv", gameIds)
      .flatMap {
        case (gameId, logFile) =>
          parseLogFile(gameId, "/*/EconomicMonitorLog_*.csv") {
            logFile.split('\n')
              // Drop header rows
              .filterNot(s => s.contains("Turn,"))
              // Drop blank lines (see ProcessEconomicCityMonitorLogs).
              .filter(_.trim.nonEmpty)
              // Extract columns of interest
              .map(line => {
                val lineArr = line.split(',').map(s => s.trim)
                (
                  gameId,
                  lineArr(0), // civ
                  lineArr(1).toInt, // turn
                  lineArr(25).toDouble, // cities
                  lineArr(26).toDouble, // trade routes
                  lineArr(28).toDouble, // city connections
                  lineArr(29).toDouble, // diplomacy
                  lineArr(30).toDouble, // religion
                  lineArr(31).toDouble, // traits
                  lineArr(32).toDouble, // total income
                  lineArr(33).toDouble, // unit maintenance,
                  lineArr(34).toDouble, // building maintenance,
                  lineArr(35).toDouble, // improvement maintenance,
                  lineArr(36).toDouble // total expenses
                )
              })
          }
      }
      .toDF("game_id", "civ", "turn", "cities", "trade_routes", "city_connections", "diplomacy", "religion",
      "traits", "total_income", "unit_maintenance", "building_maintenance", "improvement_maintenance", "total_expenses")
      .createOrReplaceTempView("gold_breakdown_by_turn")

    spark.sql(
      """
        | SELECT
        |   e.era,
        |   AVG(cities - (rt_gold / (rt.turn + 1))) AS cities,
        |   AVG(trade_routes) AS trade_routes,
        |   AVG(city_connections) AS city_connections,
        |   AVG(diplomacy) AS diplomacy,
        |   AVG(religion) AS religion,
        |   AVG(traits) AS traits,
        |   AVG(total_income) AS total_income,
        |   AVG(unit_maintenance) AS unit_maintenance,
        |   AVG(building_maintenance) AS building_maintenance,
        |   AVG(improvement_maintenance) AS improvement_maintenance,
        |   AVG(total_expenses) AS total_expenses
        | FROM
        |   gold_breakdown_by_turn g, instant_yield_running_totals rt, civ_turn_era e
        | WHERE
        |   g.game_id = rt.game_id AND
        |   g.civ = rt.civ AND
        |   g.turn = rt.turn AND
        |   g.game_id = e.game_id AND
        |   g.civ = e.civ AND
        |   g.turn = e.turn
        | GROUP BY
        |   e.era
        | ORDER BY
        |   e.era
        |""".stripMargin).createOrReplaceTempView("city_gold_breakdown_by_era")

    spark.sql(
      """
        | SELECT
        |   c.era,
        |   cities,
        |   trade_routes,
        |   city_connections,
        |   diplomacy,
        |   religion,
        |   traits,
        |   total_income,
        |   unit_maintenance,
        |   building_maintenance,
        |   improvement_maintenance,
        |   avg_building_invest,
        |   avg_unit_purchase,
        |   total_expenses
        | FROM city_gold_breakdown_by_era c, city_purchases_by_era p
        | WHERE c.era = p.era
        |""".stripMargin)
  }

  /**
   * Combines available metrics of yields to get a full breakdown of sources of each kind of yield
   *
   * Requires that the spark context contains views
   * city_economy, civ_economy, instant_yields, instant_yield_running_totals
   *
   * Additionally, creates view yields_summary_by_turn
   */
  def AggregateYieldMetrics(): DataFrame = {
    spark.sql(
      """
        | SELECT
        |   game_id,
        |   civ,
        |   turn,
        |   SUM(food) AS city_food,
        |   SUM(production) AS city_production,
        |   SUM(science) AS city_science,
        |   SUM(culture) AS city_culture,
        |   SUM(gold) AS city_gold,
        |   SUM(faith) AS city_faith,
        |   SUM(tourism) AS city_tourism,
        |   SUM(golden_age_points) AS city_golden_age_points
        | FROM
        |   city_economy
        | GROUP BY
        |   game_id,
        |   civ,
        |   turn
        |""".stripMargin).createOrReplaceTempView("city_yields_by_turn")

    spark.sql(
      """
        | SELECT
        |   game_id,
        |   civ,
        |   turn,
        |   SUM(iy_food) AS iy_food,
        |   SUM(iy_production) AS iy_production,
        |   SUM(iy_science) AS iy_science,
        |   SUM(iy_culture) AS iy_culture,
        |   SUM(iy_gold) AS iy_gold,
        |   SUM(iy_faith) AS iy_faith,
        |   SUM(iy_tourism) AS iy_tourism,
        |   SUM(iy_golden_age_points) AS iy_golden_age_points,
        |   SUM(iy_great_general_points) AS iy_great_general_points,
        |   SUM(iy_great_admiral_points) AS iy_great_admiral_points
        | FROM
        |   instant_yields
        | GROUP BY
        |   game_id,
        |   civ,
        |   turn
        |""".stripMargin).createOrReplaceTempView("instant_yields_by_turn")

    /*
     * Since instant and handicap yields don't occur every single turn, first do a left outer join to civ
     * instant yields and fill the nulls with 0 so there's an entry for every turn with 0 value increase
     * for turns it didn't happen. This allows us to cleanly aggregate per-turn metrics grouped by all turns in an era
     */

    spark.sql(
      """
        | SELECT
        |   ce.game_id,
        |   ce.civ,
        |   ce.turn,
        |   cy.city_food,
        |   ce.food AS civ_food,
        |   iy.iy_food,
        |   hy.hy_food,
        |   cy.city_production,
        |   ce.production AS civ_production,
        |   iy.iy_production,
        |   0 AS hy_production,
        |   cy.city_science,
        |   ce.science AS civ_science,
        |   iy.iy_science,
        |   hy.hy_science,
        |   cy.city_culture,
        |   ce.science AS civ_culture,
        |   iy.iy_culture,
        |   hy.hy_culture,
        |   ce.city_gold AS city_gold,
        |   ce.gold AS civ_gold,
        |   iy.iy_gold,
        |   hy.hy_gold
        | FROM
        |   civ_economy ce
        |   LEFT OUTER JOIN city_yields_by_turn cy
        |     ON ce.game_id = cy.game_id AND ce.civ = cy.civ AND ce.turn = cy.turn
        |   LEFT OUTER JOIN instant_yields_by_turn iy
        |     ON ce.game_id = iy.game_id AND ce.civ = iy.civ AND ce.turn = iy.turn
        |   LEFT OUTER JOIN handicap_yields hy
        |     ON ce.game_id = hy.game_id AND ce.civ = hy.civ AND ce.turn = hy.turn
        |""".stripMargin)
      .na.fill(0)
      .createOrReplaceTempView("turn_yield_records")

    val yields = List("food", "production", "gold", "science", "culture")
    val sources = List("civ_", "city_", "iy_", "hy_")
    val tyCols = yields.flatMap(yieldType => sources.map(source => source + yieldType))
    val aggSql = tyCols.map(tyCol => s"AVG($tyCol) AS $tyCol").mkString(",")

    val yieldsDF = spark.sql(
      s"""
        | SELECT
        |  game_id, civ, turn,
        |  $aggSql
        | FROM turn_yield_records
        | GROUP BY game_id, civ, turn
        |""".stripMargin)
    yieldsDF.createOrReplaceTempView("yields_summary_by_turn")
    yieldsDF
  }

  /**
   * Combines available metrics of yields to get a full breakdown of sources of each kind of yield
   *
   * Requires that the spark context contains views city_economy, civ_economy, instant_yields, yields_summary_by_turn
   *
   * Additionally, creates view yields_summary_by_era
   */
  def AggregateCoreYieldSourcesByEra(): DataFrame = {
    val aggSQL = List("food", "production", "gold", "science", "culture")
      .map(yieldType =>
        s"""
           | AVG(city_$yieldType) AS city_$yieldType,
           | AVG(civ_$yieldType - city_$yieldType) AS misc_$yieldType,
           | AVG(iy_$yieldType) AS iy_$yieldType,
           | ${if (yieldType.equals("production")) "0 AS hy_production," else "AVG(hy_" + yieldType + ") AS hy_" + yieldType + "," }
           | AVG(civ_$yieldType + iy_$yieldType + ${if (yieldType.equals("production")) 0 else "hy_" + yieldType}) AS total_$yieldType
           | ${if (!yieldType.equals("culture")) "," else ""}
           |""".stripMargin)
      .mkString("")

    val yieldsSourcesByEraDF = spark.sql(
      s"""
        | SELECT
        |   era,
        |   $aggSQL
        | FROM
        |   yields_summary_by_turn yt, civ_turn_era e
        | WHERE
        |   yt.game_id = e.game_id AND
        |   yt.civ = e.civ AND
        |   yt.turn = e.turn
        | GROUP BY era
        | ORDER BY era
        |""".stripMargin)
    yieldsSourcesByEraDF.createOrReplaceTempView("yields_summary_by_era")
    yieldsSourcesByEraDF
  }

  def AggregateCivEconomyByEra(): DataFrame = {
    val civEconomyByEraDF = spark.sql(
      """
        | SELECT
        |   ce.game_id,
        |   ce.civ,
        |   ce.era,
        |   COUNT(*) AS turns_in_era,
        |   AVG(ce.city_count) AS city_count_avg,
        |   AVG(ce.population) AS population_avg,
        |   AVG(ce.policies_acquired) AS policies_acquired_avg,
        |   AVG(ce.workers) AS workers_avg,
        |   AVG(ce.happiness) AS happiness_avg,
        |   AVG(ce.trade_units_active) AS trade_units_active_avg,
        |   SUM(ce.unit_maintenance) AS unit_maintenance_total,
        |   SUM(ce.building_maintenance) AS building_maintenance_total,
        |   SUM(ce.improvement_maintenance) AS improvement_maintenance_total,
        |   SUM(ce.food + iy_food + hy_food) AS food_total,
        |   SUM(ce.production + iy_production) AS production_total,
        |   SUM(ce.gold + iy_gold + hy_gold) AS gold_total,
        |   SUM(ce.science + iy_science + hy_science) AS science_total,
        |   SUM(ce.culture + iy_culture + hy_culture) AS culture_total,
        |   SUM(ce.faith + iy_faith) AS faith_total,
        |   SUM(ce.tourism + iy_tourism) AS tourism_total,
        |   SUM(ce.golden_age_points + iy_golden_age_points) AS golden_age_points_total,
        |   SUM(iy_great_general_points) AS great_general_points_total,
        |   SUM(iy_great_admiral_points) AS great_admiral_points_total
        | FROM
        |   civ_economy ce
        |   LEFT OUTER JOIN instant_yields_by_turn iy
        |     ON ce.game_id = iy.game_id AND ce.civ = iy.civ AND ce.turn = iy.turn
        |   LEFT OUTER JOIN handicap_yields hy
        |     ON ce.game_id = hy.game_id AND ce.civ = hy.civ AND ce.turn = hy.turn
        | GROUP BY
        |   ce.game_id,
        |   ce.civ,
        |   ce.era
        | ORDER BY
        |   ce.game_id,
        |   ce.civ,
        |   ce.era
        |""".stripMargin)
    civEconomyByEraDF.createOrReplaceTempView("civ_economy_by_era")
    civEconomyByEraDF
  }

  /**
   * Processes PlayerHomelandAILog_*.csv files and returns a dataframe of city purchases,
   * one row per game_id, civ, turn, purchase
   *
   * Additionally, registers the dataframe under the Spark SQL temporary view "city_purchases"
   *
   * @param sc        - the spark context object
   * @param inputPath - base path of the logs
   * @return Spark Dataframe containing processed log rows
   */
  def ProcessHomelandAILogs(
      sc: SparkContext,
      inputPath: String,
      gameIds: Option[Set[String]] = None
  ): DataFrame = {
    val cityPurchasesDF = getGameIdLogContentsRDD(sc, inputPath, "/*/PlayerHomelandAILog_*.csv", gameIds)
      .flatMap {
        case (gameId, logFile) =>
          parseLogFile(gameId, "/*/PlayerHomelandAILog_*.csv") {
            logFile.split('\n')
              // Inclusive content filter — only purchase events have the
              // fields we read by index below.
              .filter(s => s.contains("MOD - Buying unit") || s.contains("MOD - Investing in building"))
              // Extract columns of interest
              .map(line => {
                val lineArr = line.split(',').map(s => s.trim)
                val purchaseType = if (line.contains("building")) "building" else "unit"
                val costStartIdx = line.indexOf("Cost:")
                val costEndIdx = line.indexOf(", Balance")
                val cost = line.substring(costStartIdx + 5, costEndIdx).trim.toInt

                (
                  gameId,
                  lineArr(0).toInt, // turn
                  lineArr(1), // civ
                  purchaseType,
                  cost
                )
              })
          }
      }
      .toDF("game_id", "turn", "civ", "type", "cost")

    cityPurchasesDF.createOrReplaceTempView("city_purchases")
    cityPurchasesDF
  }

  def AggregateCityPurchasesByEra(): DataFrame = {
    spark.sql(
      """
        | SELECT
        |   e.game_id,
        |   e.civ,
        |   e.era,
        |   e.turn,
        |   c.type,
        |   c.cost
        | FROM
        |   civ_turn_era e LEFT OUTER JOIN city_purchases c
        | ON
        |   c.game_id = e.game_id AND
        |   c.civ = e.civ AND
        |   c.turn = e.turn
        |""".stripMargin).na.fill(0)
      .groupBy("game_id", "civ", "turn", "era")
      .pivot("type")
      .sum("cost")
      .na.fill(0)
      .orderBy("game_id", "civ", "turn")
      .createOrReplaceTempView("city_purchases_all_turns")


    val cityPurchasesByEraDf = spark.sql(
      """
        | SELECT
        |   era,
        |   AVG(building) AS avg_building_invest,
        |   AVG(unit) AS avg_unit_purchase
        | FROM city_purchases_all_turns
        | GROUP BY
        |   era
        | ORDER BY
        |   era
        |""".stripMargin)

    cityPurchasesByEraDf.createOrReplaceTempView("city_purchases_by_era")
    cityPurchasesByEraDf
  }
}
