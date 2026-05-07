package civ5

import civ5.Util.{getGameIdLogContentsRDD, parseLogFile}
import org.apache.spark.SparkContext
import org.apache.spark.sql.DataFrame
import SparkJob.spark.implicits._

object Religion extends SparkJob {
  type ReligionChoiceInstance = (
    String, // Game ID
    String, // Civ
    String, // Religion Type
    Int, // Turn
    String // belief
  )
  /**
   * Processes ReligionLog.csv files and returns a dataframe of religion choice rows
   *
   * Additionally, registers the dataframe under the Spark SQL temporary view "religion_choice_stats"
   *
   * @param sc - the spark context object
   * @param inputPath - base path of the logs
   * @return Spark Dataframe containing processed log rows
   */
  def ProcessReligionLogs(
      sc: SparkContext,
      inputPath: String,
      gameIds: Option[Set[String]] = None
  ): DataFrame = {
    val religionChoiceDF = getGameIdLogContentsRDD(sc, inputPath, "/*/ReligionLog.csv", gameIds)
      .flatMap {
        case (gameId, logFile) =>
          parseLogFile(gameId, "/*/ReligionLog.csv") {
          val logLines = logFile
            .split('\n')
            .map(s => s.trim)
            .filter(line => {
              line.contains("CHOSEN") || line.contains("PANTHEON FOUNDED") || line.contains("RELIGION FOUNDED") ||
                line.contains("RELIGION ENHANCED") || line.contains("REFORMATION BELIEF ADDED")
            })
            // Extract columns of interest
            .map(line => {
              val lineArr = line.split(',').toIterator.map(s => s.trim).toList
              (
                lineArr(0).toInt, // turn
                lineArr(2), // civ
                lineArr(3), // event
                if (lineArr.length < 5) "" else lineArr(4) // details
              )
            })

          // Choices are logged over several rows, first the perks chosen and then by whom and where/when
          // keep track of chosen perks while iterating through the rows
          var chosenPerks = List[String]()

          logLines.foldLeft(List[ReligionChoiceInstance]()) {
            case (acc, (_, _, "CHOSEN", details: String)) =>
              chosenPerks = chosenPerks :+ details
              acc
            case (acc, (turn: Int, civ: String, "PANTHEON FOUNDED", _)) =>
              val perk = chosenPerks.head
              chosenPerks = List[String]()
              acc :+ (gameId, civ, "pantheon", turn, perk)
            case (acc, (turn: Int, civ: String, "RELIGION FOUNDED", _)) =>
              val perk1 = chosenPerks.head
              val perk2 = chosenPerks(1)
              chosenPerks = List[String]()
              acc ++ List(
                (gameId, civ, "religion_founded", turn, perk1),
                (gameId, civ, "religion_founded", turn, perk2)
              )
            case (acc, (turn: Int, civ: String, "RELIGION ENHANCED", _)) =>
              val perk1 = chosenPerks.head
              val perk2 = chosenPerks(1)
              chosenPerks = List[String]()
              acc ++ List(
                (gameId, civ, "religion_enhanced", turn, perk1),
                (gameId, civ, "religion_enhanced", turn, perk2)
              )
            case (acc, (turn: Int, civ: String, "REFORMATION BELIEF ADDED", _)) =>
              val perk = chosenPerks.head
              chosenPerks = List[String]()
              acc :+ (gameId, civ, "religion_reformed", turn, perk)
          }
          }
      }
      .toDF("game_id", "civ", "type", "turn", "belief")

    religionChoiceDF.createOrReplaceTempView("religion_choices")
    religionChoiceDF
  }

  def AggregateReligionLogs(): DataFrame = {
    val religionStatsDF = spark.sql(
      """
        | SELECT
        |   r.type,
        |   r.belief,
        |   AVG(r.turn) AS avg_turn,
        |   COUNT(*) as chosen_count,
        |   SUM(CASE WHEN g.victory_type IS NULL THEN 0 ELSE 1 END) as wins
        | FROM
        |   religion_choices r
        | LEFT OUTER JOIN
        |   game_result g
        | ON r.game_id = g.game_id AND
        |   r.civ = g.victory_civ
        | GROUP BY
        |   r.type, r.belief
        | ORDER BY
        |   r.type, r.belief
        |""".stripMargin)

    religionStatsDF.createOrReplaceTempView("religion_stats")
    religionStatsDF
  }
}
