package civ5

import civ5.Util.{getGameIdLogContentsRDD, parseLogFile}
import org.apache.spark.SparkContext
import org.apache.spark.sql.DataFrame
import org.apache.spark.sql.functions.when

import SparkJob.spark.implicits._

object GameResult extends SparkJob {
  /**
   * Processes GameResult_Log.csv files and returns a dataframe of game result rows
   *
   * Additionally, registers the dataframe under the Spark SQL temporary view "game_result"
   *
   * @param sc        - the spark context object
   * @param inputPath - base path of the logs
   * @return Spark Dataframe containing processed log rows
   */
  def ProcessGameResultLogs(
      sc: SparkContext,
      inputPath: String,
      gameIds: Option[Set[String]] = None
  ): DataFrame = {
    val gameResultLogsDF = getGameIdLogContentsRDD(sc, inputPath, "/*/*GameResult_Log.csv", gameIds)
      // Map each log to a single summary tuple
      .map {
        case (gameId, logFile) =>
          parseLogFile(gameId, "/*/*GameResult_Log.csv") {
            // GameResult_Log.csv has a single header row at index 0; the
            // summary tuple lives at index 1.
            val gameResult = logFile.split('\n')(1).split(',').map(s => s.trim)
            (gameId, gameResult(0), gameResult(1), gameResult(2))
          }
      }
      .toDF("game_id", "turn", "victory_type", "victory_civ")
      // Encode victory types for column-wise aggregation
      .withColumn("culture_victory", when($"victory_type" === "Cultural", 1).otherwise(0))
      .withColumn("diplomatic_victory", when($"victory_type" === "Diplomatic", 1).otherwise(0))
      .withColumn("domination_victory", when($"victory_type" === "Domination", 1).otherwise(0))
      .withColumn("science_victory", when($"victory_type" === "Science", 1).otherwise(0))
      .withColumn("time_victory", when($"victory_type" === "Time", 1).otherwise(0))

    gameResultLogsDF.createOrReplaceTempView("game_result")
    gameResultLogsDF
  }

  /**
   * Processes GameResult_Log.csv files and returns a dataframe of records for per-civ performance per game
   * Requires that the spark context contains view game_result
   *
   * Additionally, registers the dataframe under the Spark SQL temporary view "civ_game_result"
   *
   * @param sc        - the spark context object
   * @param inputPath - base path of the logs
   * @return Spark Dataframe containing processed log rows
   */
  def ProcessCivGameResults(
      sc: SparkContext,
      inputPath: String,
      gameIds: Option[Set[String]] = None
  ): DataFrame = {
    var civGameResultDF = getGameIdLogContentsRDD(sc, inputPath, "/*/*GameResult_Log.csv", gameIds)
      // Extract per-civ information from column names of this log (first row of csv)
      .flatMap {
        case (gameId, logFile) =>
          parseLogFile(gameId, "/*/*GameResult_Log.csv") {
            val logLines = logFile.split('\n')
            (logLines(0).split(',') zip logLines(1).split(','))
              .drop(3)
              .map { case (civ, score) => (gameId, civ.trim, score.trim) }
          }
      }
      .toDF("game_id", "civ", "score")
    civGameResultDF.createOrReplaceTempView("civ_game_result")

    civGameResultDF = spark.sql(
      """
        | SELECT
        |   cgr.game_id,
        |   cgr.civ,
        |   gr.turn AS game_end_turn,
        |   cgr.score,
        |   gr2.victory_type,
        |   gr2.culture_victory,
        |   gr2.diplomatic_victory,
        |   gr2.domination_victory,
        |   gr2.science_victory,
        |   gr2.time_victory
        | FROM
        |   civ_game_result cgr
        |   LEFT OUTER JOIN game_result gr2
        |     ON cgr.game_id = gr2.game_id AND
        |        cgr.civ = gr2.victory_civ
        |   INNER JOIN game_result gr
        |     ON cgr.game_id = gr.game_id
        |""".stripMargin)
    civGameResultDF.createOrReplaceTempView("civ_game_result")

    civGameResultDF
  }

  /**
   * Aggregates the game_result table to get statistics on each victory type
   *
   * Requires that the spark context contains view game_result
   *
   * @return Spark Dataframe containing aggregated rows
   */
  def AggregateGameResultVictories(): DataFrame = {
    spark.sql(
      """
        | SELECT
        |   victory_type,
        |   COUNT(*) AS count,
        |   AVG(turn) AS avg_turn,
        |   STDDEV(turn) AS stddev_turn
        | FROM game_result
        | GROUP BY victory_type
        |""".stripMargin
    )
  }

  /**
   * Augments game-civ result records with map state information: the percentage of tiles and cities the civ
   * owned when the game ended.
   * Creates or replaces the augmented_game_result view
   *
   * Requires that the spark context contains views civ_game_result and effective_ownership_by_game_turn
   *
   * @return Spark Dataframe containing aggregated rows
   */
  def AugmentGameResultWithMapMetrics(): Unit = {
    spark.sql(
      """
        | SELECT
        |   cgr.*,
        |   eo.tiles_owned_percentage,
        |   eo.cities_owned_percentage
        | FROM
        |   civ_game_result cgr LEFT OUTER JOIN effective_ownership_by_game_turn eo
        |   ON
        |     cgr.game_id = eo.game_id AND
        |     cgr.civ = eo.effective_owner AND
        |     cgr.game_end_turn = eo.turn
        |""".stripMargin).createOrReplaceTempView("augmented_game_result")
  }

  /**
   * Aggregates game records and map tile records to calculate earliest instances in a game, if it
   * exists, of a civ attaining 2/3rd ownership of tiles and cities.
   *
   * @return authorityVictoryDf: Dataframe containing all authority victories, one per row
   */
  def AggregateAuthorityVictories(): DataFrame = {
    val thrsh = "0.66666" // threshold at which this control of territory and cities wins
    // Classify pseudo victories while also joining with game-turn totals to get percentages
    spark.sql(
      s"""
         | SELECT
         |   a.game_id AS game_id, a.effective_owner AS owner_nation, a.turn AS turn,
         |   a.tiles_owned / t.tiles_owned AS tiles_owned,
         |   a.cities_owned / t.cities_owned AS cities_owned,
         |   (CASE WHEN a.tiles_owned / t.tiles_owned > $thrsh AND a.cities_owned / t.cities_owned > $thrsh THEN 1 ELSE 0 END)
         |     AS pseudo_victory
         | FROM
         | effective_ownership_by_game_turn a INNER JOIN ownership_by_game_turn t
         |   ON a.game_id = t.game_id AND a.turn = t.turn
         |""".stripMargin).createOrReplaceTempView("pct_totals")

    spark.sql(
      """
        | SELECT
        |   game_id, owner_nation,
        |   MIN(turn) as turn
        | FROM
        |   pct_totals
        | WHERE pseudo_victory = 1
        | GROUP BY
        |   game_id, owner_nation
        |""".stripMargin).createOrReplaceTempView("first_occurrence")

    val authorityVictoryDf = spark.sql(
      """
        | SELECT
        |   pct_totals.*
        | FROM
        |   pct_totals INNER JOIN first_occurrence
        | ON pct_totals.game_id = first_occurrence.game_id
        |   AND pct_totals.turn = first_occurrence.turn
        |   AND pct_totals.owner_nation = first_occurrence.owner_nation
        |""".stripMargin)
    authorityVictoryDf.createOrReplaceTempView("authority_victories")
    authorityVictoryDf
  }
}
