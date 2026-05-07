package civ5

import civ5.Util.{getGameIdLogContentsRDD, parseLogFile}
import org.apache.spark.SparkContext
import org.apache.spark.sql.DataFrame

import org.apache.spark.sql.expressions.Window
import org.apache.spark.sql.functions._

import SparkJob.spark.implicits._

object Policies extends SparkJob {
  /**
   * Processes PolicyAILog_*.csv files and returns a dataframe of policy choice rows
   *
   * Additionally, registers the dataframe under the Spark SQL temporary view "branch_choice_stats"
   *
   * @param sc - the spark context object
   * @param inputPath - base path of the logs
   * @return Spark Dataframe containing processed log rows
   */
  def ProcessPolicyLogs(
      sc: SparkContext,
      inputPath: String,
      gameIds: Option[Set[String]] = None
  ): DataFrame = {
    val policyChoiceDF = getGameIdLogContentsRDD(sc, inputPath, "/*/PolicyAILog_*.csv", gameIds)
      .flatMap {
        case (gameId, logFile) =>
          parseLogFile(gameId, "/*/PolicyAILog_*.csv") {
            logFile
              .split('\n')
              .map(s => s.trim)
              .filter(line => {
                line.contains("CHOSEN")
              })
              .filter(line => line.contains("Branch"))
              // Extract columns of interest
              .map(line => {
                val lineArr = line.split(',').toIterator.map(s => s.trim).toList
                (gameId,
                  lineArr(0).toInt,
                  lineArr(1),
                  lineArr(3).split(' ')(1).toInt // extract policy tree number from string of form "Branch 2"
                )
              })
          }
      }
      .toDF("game_id", "turn", "civ", "branch")

    policyChoiceDF.createOrReplaceTempView("branch_choice_stats")
    policyChoiceDF
  }

  def ProcessPolicyChoices(
      sc: SparkContext,
      inputPath: String,
      gameIds: Option[Set[String]] = None
  ): DataFrame = {
    val policyChoicesDF = getGameIdLogContentsRDD(sc, inputPath, "/*/PolicyAILog_*.csv", gameIds)
      .flatMap {
        case (gameId, logFile) =>
          parseLogFile(gameId, "/*/PolicyAILog_*.csv") {
            logFile
              .split('\n')
              .map(s => s.trim)
              .filter(line => {
                line.contains("CHOSEN")
              })
              // Extract columns of interest
              .map(line => {
                val lineArr = line.split(',').toIterator.map(s => s.trim).toList
                (gameId,
                  lineArr(0).toInt,
                  lineArr(1),
                  lineArr(3)
                )
              })
          }
      }
      .toDF("game_id", "turn", "civ", "item")

    val windowSpec = Window
      .partitionBy("game_id", "civ")
      .orderBy("turn")

    val rankedPolicyChoicesDF = policyChoicesDF.withColumn("pick_order", row_number().over(windowSpec))

    rankedPolicyChoicesDF.createOrReplaceTempView("policy_choices")
    rankedPolicyChoicesDF
  }

  /**
   * Augments branch choices with their game result by performing a left outer join to
   * game results. This results in a record of the win type for civ-choice instances that won
   * and a null in victory_type column for civ-choices that did not
   *
   * Requires that the spark context contains views branch_choice_stats and game_result
   * @return Spark Dataframe containing aggregated rows
   */
  def AugmentPolicyBranchChoicesWithGameResult(): DataFrame = {
    spark.sql(
      """
        | SELECT
        |    bcs.game_id,
        |    bcs.branch,
        |    bcs.civ,
        |    bcs.turn,
        |    v.victory_type
        | FROM branch_choice_stats bcs
        |   LEFT OUTER JOIN game_result v
        | ON bcs.civ = v.victory_civ AND
        |   bcs.game_id = v.game_id
        |""".stripMargin).toDF()
  }
}
