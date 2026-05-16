package civ5

import SparkJob.spark.implicits._
import civ5.Util.{getGameIdLogContentsRDD, parseLogFile}
import org.apache.spark.SparkContext
import org.apache.spark.sql.{DataFrame, Row}

import scala.collection.mutable

object InstantYields extends SparkJob {
  private val instantYieldTypes = Seq(
    "Food",
    "Production",
    "Science",
    "Gold",
    "Culture",
    "Faith",
    "Tourism",
    "Golden Age Points",
    "Border Growth Points",
    "Great General Points",
    "Great Admiral Points"
  )

  private val type1Regex =
    "VP AI DIFFICULTY BONUS FROM (.*) - Received Handicap Bonus: GOLD \\(([0-9]+(?:\\.[0-9]+)?)\\)(?:, )?CULTURE \\(([0-9]+(?:\\.[0-9]+)?)\\)(?:, )?SCIENCE \\(([0-9]+(?:\\.[0-9]+)?)\\)\\.".r
  private val type2Regex =
    "VP AI DIFFICULTY BONUS FROM (.*) - Received Handicap Bonus: FOOD \\(([0-9]+(?:\\.[0-9]+)?);.*\\)GOLD \\(([0-9]+(?:\\.[0-9]+)?)\\)(CULTURE|SCIENCE) \\(([0-9]+(?:\\.[0-9]+)?)\\)\\.".r
  private val type3Regex =
    "VP AI DIFFICULTY BONUS FROM (.*) - Received Handicap Bonus: FOOD \\(([0-9]+(?:\\.[0-9]+)?);.*\\)GOLD \\(([0-9]+(?:\\.[0-9]+)?)\\)CULTURE \\(([0-9]+(?:\\.[0-9]+)?)\\)SCIENCE \\(([0-9]+(?:\\.[0-9]+)?)\\)\\.".r
  private val type4Regex
  = "VP AI DIFFICULTY BONUS FROM (.*) - Received Handicap Bonus \\(([0-9]+(?:\\.[0-9]+)?) in Yields\\):.*".r
  private val type5Regex =
    "VP AI DIFFICULTY BONUS FROM (.*) - Received Handicap Bonus: CULTURE \\(([0-9]+(?:\\.[0-9]+)?)\\)SCIENCE \\(([0-9]+(?:\\.[0-9]+)?)\\)\\.".r


  /**
   * Processes InstantYieldSummary.csv files and returns a dataframe of instant yield rows,
   * one row per game_id, civ, turn, yield type/value combination
   *
   * Additionally, registers the dataframe under the Spark SQL temporary view "instant_yields"
   *
   * @param sc        - the spark context object
   * @param inputPath - base path of the logs
   * @return Spark Dataframe containing processed log rows
   */

  def ProcessInstantYieldLogs(
      sc: SparkContext,
      inputPath: String,
      gameIds: Option[Set[String]] = None
  ): DataFrame = {
    val df: DataFrame = sc.parallelize(Seq((1, 0): (Integer, Integer), (1, 0): (Integer, Integer), (null, 0): (Integer, Integer), (0, 0): (Integer, Integer))).map(x => (x._1, 0)).toDF("value", "z")
    getGameIdLogContentsRDD(sc, inputPath, "/*/InstantYieldSummary.csv", gameIds)
      .flatMap {
        case (gameId, logFile) =>
          parseLogFile(gameId, "/*/InstantYieldSummary.csv") {
            logFile.split('\n')
              // Drop header rows (defensive against future VP versions adding
              // a header row to a previously-headerless log).
              .filterNot(s => s.contains("Turn,"))
              // Extract columns of interest
              .map(line => {
                val lineArr = line.split(',').map(s => s.trim)
                (
                  gameId,
                  lineArr(0).toInt, // turn
                  lineArr(1), // civ
                  // Parse "Instant Yield Type: Border Growth" format strings to get reason
                  // Also don't differentiate between retroactive reasons
                  lineArr(3).drop(20).replace(" Retro", "").replace("Instant", "Building Completion Effect"), // reason
                  // Parse "Yield Type: Food" format strings to get yield type
                  lineArr(4).drop(12), // yield
                  // Parse "Value: 315" format strings to get yield amount
                  lineArr(5).drop(7).toDouble // amount
                )
              })
          }
      }
      .toDF("game_id", "turn", "civ", "reason", "yield", "amount")
      .groupBy("game_id", "turn", "civ", "reason")
      .pivot("yield", instantYieldTypes)
      .sum("amount")
      .withColumnRenamed("Food", "iy_food")
      .withColumnRenamed("Production", "iy_production")
      .withColumnRenamed("Science", "iy_science")
      .withColumnRenamed("Gold", "iy_gold")
      .withColumnRenamed("Culture", "iy_culture")
      .withColumnRenamed("Faith", "iy_faith")
      .withColumnRenamed("Tourism", "iy_tourism")
      .withColumnRenamed("Golden Age Points", "iy_golden_age_points")
      .withColumnRenamed("Border Growth Points", "iy_border_growth_points")
      .withColumnRenamed("Great General Points", "iy_great_general_points")
      .withColumnRenamed("Great Admiral Points", "iy_great_admiral_points")
      .na.fill(0)
      // Yields are integer-valued in Civ V; pivot+sum gives Double which
      // breaks downstream callers that use row.getLong(...). Cast back to Long.
      .selectExpr(
        "game_id", "turn", "civ", "reason",
        "CAST(iy_food AS BIGINT) AS iy_food",
        "CAST(iy_production AS BIGINT) AS iy_production",
        "CAST(iy_science AS BIGINT) AS iy_science",
        "CAST(iy_gold AS BIGINT) AS iy_gold",
        "CAST(iy_culture AS BIGINT) AS iy_culture",
        "CAST(iy_faith AS BIGINT) AS iy_faith",
        "CAST(iy_tourism AS BIGINT) AS iy_tourism",
        "CAST(iy_golden_age_points AS BIGINT) AS iy_golden_age_points",
        "CAST(iy_border_growth_points AS BIGINT) AS iy_border_growth_points",
        "CAST(iy_great_general_points AS BIGINT) AS iy_great_general_points",
        "CAST(iy_great_admiral_points AS BIGINT) AS iy_great_admiral_points"
      )
      .createOrReplaceTempView("instant_yields")


    val instantYieldDF = spark.sql(
      """
        | SELECT
        |   iy.game_id,
        |   iy.turn,
        |   e.era,
        |   iy.civ,
        |   iy.reason,
        |   iy_food, iy_production, iy_science, iy_gold, iy_culture, iy_faith, iy_tourism,
        |   iy_golden_age_points, iy_border_growth_points, iy_great_general_points, iy_great_admiral_points
        | FROM
        |   instant_yields iy, civ_turn_era e
        | WHERE
        |   iy.game_id = e.game_id AND
        |   iy.civ = e.civ AND
        |   iy.turn = e.turn
        |""".stripMargin)
    instantYieldDF.createOrReplaceTempView("instant_yields")
    instantYieldDF
  }

  /**
   * Processes DifficultyHandicapLog.csv to get a record of all handicap yield instances,
   * one per event
   *
   * Registers under view "handicap_yields"
   *
   * @param sc
   * @param inputPath
   * @return
   */
  def ProcessHandicapYieldLogs(
      sc: SparkContext,
      inputPath: String,
      gameIds: Option[Set[String]] = None
  ): DataFrame = {
    // There are two different parts of the dll code that write to this log and don't use the same format, so
    // handle it by case
    getGameIdLogContentsRDD(sc, inputPath, "/*/DifficultyHandicapLog.csv", gameIds)
      .flatMap {
        case (gameId, logFile) =>
          parseLogFile(gameId, "/*/DifficultyHandicapLog.csv") {
            logFile.split('\n')
              // Drop header rows (defensive — the regex chain below would
              // otherwise throw "unknown handicap log entry format").
              .filterNot(s => s.contains("Turn,"))
              // Extract columns of interest
              .map(line => {
              val lineArr = line.split(',').map(s => s.trim)
              // We want to treat the rest of the so-called csv file as a single value
              val handicapYieldsInfoStr = lineArr.drop(2).mkString("")

              val (reason: String, gold: Double, food: Double, culture: Double, science: Double) =
                if (handicapYieldsInfoStr.contains("Received Handicap Bonus: GOLD")) {
                  val type1Regex(reason, gold, culture, science) = handicapYieldsInfoStr
                  (reason, gold.toDouble, 0.0, culture.toDouble, science.toDouble)
                }
                else if (
                  handicapYieldsInfoStr.contains("Received Handicap Bonus: FOOD") &&
                    handicapYieldsInfoStr.contains("CULTURE") &&
                    handicapYieldsInfoStr.contains("SCIENCE")
                ) {
                  val type3Regex(reason, food, gold, culture, science) = handicapYieldsInfoStr
                  (reason, gold.toDouble, food.toDouble, culture.toDouble, science.toDouble)
                }
                else if (handicapYieldsInfoStr.contains("Received Handicap Bonus: FOOD")) {
                  val type2Regex(reason, food, gold, yieldType, amount) = handicapYieldsInfoStr
                  (reason, gold.toDouble, food.toDouble,
                    if (yieldType.equals("CULTURE")) amount.toDouble else 0.0,
                    if (yieldType.equals("SCIENCE")) amount.toDouble else 0.0
                  )
                }
                else if (handicapYieldsInfoStr.contains("Received Handicap Bonus: CULTURE")) {
                  val type5Regex(reason, culture, science) = handicapYieldsInfoStr
                  (reason, 0.0, 0.0, culture.toDouble, science.toDouble)
                }
                else if (handicapYieldsInfoStr.contains("Received Handicap Bonus (")) {
                  val type4Regex(reason, amount) = handicapYieldsInfoStr
                  (
                    reason,
                    if (handicapYieldsInfoStr.contains("GOLD")) amount.toDouble else 0.0,
                    if (handicapYieldsInfoStr.contains("FOOD")) amount.toDouble else 0.0,
                    if (handicapYieldsInfoStr.contains("CULTURE")) amount.toDouble else 0.0,
                    if (handicapYieldsInfoStr.contains("SCIENCE")) amount.toDouble else 0.0
                  )
                } else {
                  throw new Exception("unknown handicap log entry format\n" + handicapYieldsInfoStr)
                }
              // combine stuff from the start of the line and the later information extraction
              (
                gameId,
                lineArr(0), // civ
                lineArr(1).toInt, // turn
                reason,
                gold,
                food,
                culture,
                science
              )
            })
          }
      }
      .toDF("game_id", "civ", "turn", "reason", "hy_gold", "hy_food", "hy_culture", "hy_science")
      .createOrReplaceTempView("handicap_yields")

    val handicapYieldDF = spark.sql(
      """
        | SELECT
        |   hy.game_id,
        |   hy.turn,
        |   e.era,
        |   hy.civ,
        |   hy.reason,
        |   hy_gold, hy_food, hy_culture, hy_science
        | FROM
        |   handicap_yields hy, civ_turn_era e
        | WHERE
        |   hy.game_id = e.game_id AND
        |   hy.civ = e.civ AND
        |   hy.turn = e.turn
        |""".stripMargin)

    handicapYieldDF.createOrReplaceTempView("handicap_yields")
    handicapYieldDF 
  }

  /**
   * Creates view "instant_yield_running_totals" that contains the total amount of each instant yield receieved
   * in the game up to that turn, one row per game_id/civ/nation with yield types as feature columns
   */
  def CalculateInstantYieldCumulativeSums(): Unit = {
    spark.sql(
        """
          | SELECT
          |   game_id,
          |   civ,
          |   turn,
          |   SUM(iy_food),
          |   SUM(iy_production),
          |   SUM(iy_gold),
          |   SUM(iy_science),
          |   SUM(iy_culture)
          | FROM instant_yields
          | GROUP BY game_id, civ, turn
          | ORDER BY game_id, civ, turn
          |""".stripMargin)
      .groupByKey(row => (row.getString(0), row.getString(1)))
      .flatMapGroups {
        case ((gameId, civ), rows) =>
          // Traverse all the rows for this gameId/civ, creating a map of turns to yield incomes
          val turnToYieldMap = rows.map(row => {
              val turn = row.getInt(2)
              val food = if (row.isNullAt(3)) 0 else row.getLong(3)
              val production = if (row.isNullAt(4)) 0 else row.getLong(4)
              val gold = if (row.isNullAt(5)) 0 else row.getLong(5)
              val science = if (row.isNullAt(6)) 0 else row.getLong(6)
              val culture = if (row.isNullAt(7)) 0 else row.getLong(7)

              (turn, Map(
                "food" -> food,
                "production" -> production,
                "gold" -> gold,
                "science" -> science,
                "culture" -> culture
              ))
            })
            .toMap

          val yieldTypes = List("food", "production", "gold", "science", "culture")
          val runningTotals = scala.collection.mutable.Map[String, Long]() ++=
            yieldTypes.map(yieldType => yieldType -> 0L)

          List.range(1, 501).map(turn => {
            // Update running totals based on the turns instant yield incomes if any happened on this turn
            yieldTypes.foreach(yieldType =>
              runningTotals(yieldType) = runningTotals(yieldType) + (if (turnToYieldMap.contains(turn))
                turnToYieldMap(turn).getOrElse(yieldType, 0L)
              else 0L)
            )

            // Emit a row for every turn and the running total of each yield to that point
            (
              gameId,
              civ,
              turn,
              runningTotals("food"),
              runningTotals("production"),
              runningTotals("gold"),
              runningTotals("science"),
              runningTotals("culture")
            )
          })
      }
      .toDF("game_id", "civ", "turn", "rt_food", "rt_production", "rt_gold", "rt_science", "rt_culture")
      .createOrReplaceTempView("instant_yield_running_totals")
  }

  def AggregateInstantYieldSources(): List[(String, DataFrame)] = {
    val nGames = spark.sql("SELECT COUNT(DISTINCT(game_id)) FROM instant_yields").first()(0)

    val yields = List("food", "production", "gold", "science", "culture")


    yields.map(yieldType => {
      spark.sql(
        s"""
           | SELECT
           |   game_id,
           |   era,
           |   reason AS trigger,
           |   civ,
           |   COUNT(*) AS times_triggered,
           |   AVG(iy_$yieldType) AS sanity_iy_per_era
           | FROM
           |   instant_yields
           | WHERE iy_$yieldType > 0
           | GROUP BY
           |   game_id,
           |   era,
           |   trigger,
           |   civ
           |""".stripMargin).createOrReplaceTempView("times_triggered_by_civ")
      spark.sql(
        """
          | SELECT
          |   era,
          |   trigger,
          |   COUNT(*) AS sanity_count,
          |   AVG(times_triggered) AS sanity_avg,
          |   STDDEV(times_triggered) AS stddev_times_triggered,
          |   AVG(sanity_iy_per_era) AS sanity_iy_per_era
          | FROM times_triggered_by_civ
          | GROUP BY
          |   era,
          |   trigger
          |""".stripMargin).createOrReplaceTempView("trigger_frequency_stats")

      spark.sql(
        s"""
          | SELECT
          |   era,
          |   reason AS trigger,
          |   AVG(iy_$yieldType) AS avg_iy_$yieldType,
          |   COUNT(*) AS times_triggered
          | FROM instant_yields
          | WHERE
          |   iy_$yieldType > 0
          | GROUP BY
          |   era, trigger
          | ORDER BY
          |   era, times_triggered desc
          |""".stripMargin).createOrReplaceTempView("yield_summary_by_trigger")

      (yieldType, spark.sql(
        s"""
           | SELECT
           |   ys.era,
           |   ys.trigger,
           |   ys.avg_iy_$yieldType,
           |   tf.sanity_iy_per_era,
           |   ys.times_triggered,
           |   tf.sanity_count,
           |   ys.times_triggered / 8 / $nGames AS avg_times_triggered,
           |   tf.sanity_avg,
           |   tf.stddev_times_triggered
           | FROM yield_summary_by_trigger ys
           | LEFT JOIN trigger_frequency_stats tf
           | ON
           |   tf.era = ys.era AND
           |   tf.trigger = ys.trigger
           | ORDER BY ys.era, ys.trigger
           |""".stripMargin)
      )
    })
  }

  def AggregateHandicapYieldSources(): List[(String, DataFrame)] = {
    val nGames = spark.sql("SELECT COUNT(DISTINCT(game_id)) FROM handicap_yields").first()(0)

    val yields = List("food", "gold", "science", "culture")

    yields.map(yieldType => (yieldType, spark.sql(
      s"""
         | SELECT
         |   era,
         |   reason AS trigger,
         |   AVG(hy_$yieldType) AS avg_hy_$yieldType,
         |   COUNT(*) / $nGames / 8 AS avg_times_triggered
         | FROM handicap_yields hy
         | WHERE
         |   hy_$yieldType > 0
         | GROUP BY
         |   era, reason
         | ORDER BY
         |   era, avg_times_triggered desc
         |""".stripMargin)))
  }
}