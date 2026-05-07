package civ5

import civ5.Util.{getGameIdLogContentsRDD, parseLogFile}
import org.apache.spark.SparkContext
import org.apache.spark.sql.DataFrame
import SparkJob.spark.implicits._
import civ5.Constants.TECH_TO_GRIDX_MAP
import civ5.Technologies.TechResearchInstance

object Vassalage extends SparkJob {
  /**
   * Processes DiplomacyAI_TradeAgreements_Log_.csv files and returns a dataframe of
   * vassalage deals, one per row
   *
   * Additionally, registers the dataframe under the Spark SQL temporary view "vassalage_deal"
   *
   * @param sc        - the spark context object
   * @param inputPath - base path of the logs
   * @return Spark Dataframe containing processed log rows
   */
  def ExtractVassalageDealsFromDiplomacyLogs(
      sc: SparkContext,
      inputPath: String,
      gameIds: Option[Set[String]] = None
  ): DataFrame = {
    val vassalageDF = getGameIdLogContentsRDD(sc, inputPath, "/*/DiplomacyAI_TradeAgreements_Log_.csv", gameIds)
      // Process each log into a vassalage trade instances
      .flatMap {
        case (gameId, logFile) =>
          parseLogFile(gameId, "/*/DiplomacyAI_TradeAgreements_Log_.csv") {
            logFile
              .split('\n')
              .filter(line => line.contains("***** Vassalage Trade *****"))
              // Extract columns of interest
              .map(line => {
                val lineArr = line.split(',').map(s => s.trim)
                (gameId, lineArr(0).toInt, lineArr(1), lineArr(2))
              })
          }
      }
      .toDF("game_id", "turn", "vassal", "master")
    vassalageDF.createOrReplaceTempView("vassalage_deal")
    vassalageDF
  }

  /**
   * Computes a map of latest (closest to game end) masters to list of vassals by game
   *
   * Requires that the spark context contains view vassalage_deal
   * @return
   */
  def ComputeVassalageMapFromDeals(): collection.Map[String, Map[String, List[String]]] = {
      spark.sql(
          """
            | WITH last_vassalage AS
            | (SELECT
            |   game_id,
            |   MAX(turn) AS turn,
            |   vassal
            | FROM vassalage_deal
            | GROUP BY game_id, vassal)
            | SELECT
            |   vassalage_deal.game_id,
            |   vassalage_deal.turn,
            |   vassalage_deal.vassal,
            |   vassalage_deal.master
            | FROM vassalage_deal INNER JOIN last_vassalage ON
            |   vassalage_deal.game_id = last_vassalage.game_id AND
            |   vassalage_deal.turn = last_vassalage.turn AND
            |   vassalage_deal.vassal = last_vassalage.vassal
            |""".stripMargin)
        .rdd
        // Set up a stripes based aggregation using master nation as the key
        .map(row => ( row(0).asInstanceOf[String], Map(row(3).asInstanceOf[String] -> List(row(2).asInstanceOf[String])) ))
        // Reduce by concatenating all vassals of a master
        .reduceByKey(
          (map1, map2) => map1 ++ map2.map { case (k, v) => k -> (v ++ map1.getOrElse(k, List())) }
        )
        .collectAsMap()
    }
}
