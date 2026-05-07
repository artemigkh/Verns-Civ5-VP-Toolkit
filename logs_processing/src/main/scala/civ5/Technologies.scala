package civ5

import civ5.Util.{getGameIdLogContentsRDD, parseLogFile}
import org.apache.spark.SparkContext
import org.apache.spark.sql.DataFrame
import SparkJob.spark.implicits._
import civ5.Constants.TECH_TO_GRIDX_MAP
object Technologies extends SparkJob  {
  type TechResearchInstance = (
    String, // Game ID
    String, // Nation
    String, // Tech
    Int, // Duration
    Int, // GridX at research time
    Int, // Start Turn
    Int  // End Turn
  )
  /**
   * Processes GameResult_Log.csv files and returns a dataframe of technology research completion record rows
   *
   * Additionally, registers the dataframe under the Spark SQL temporary view "research_instance"
   *
   * @param sc - the spark context object
   * @param inputPath - base path of the logs
   * @return Spark Dataframe containing processed log rows
   */
  def ProcessTechnologyLogs(
      sc: SparkContext,
      inputPath: String,
      gameIds: Option[Set[String]] = None
  ): DataFrame = {
    val researchDF = getGameIdLogContentsRDD(sc, inputPath, "/*/*TechAILog_*.csv", gameIds)
      // Process each log into a sequence of technology-research instances.
      //
      // Concurrency note: getGameIdLogContentsRDD is built on
      // sc.wholeTextFiles, which produces one RDD record per file -- the
      // entire file's contents is loaded into a single String element. The
      // flatMap below therefore runs over one whole TechAILog file at a
      // time. The minPartitions hint controls how many *files* are batched
      // into a task; it never splits a single file across tasks.
      //
      // This means the foldLeft is correct as long as one TechAILog file
      // contains exactly one civ's complete technology progression for the
      // game -- which holds for VP's actual log layout
      // (TechAILog_<CivOrCityState>.csv, one file per civ per game).
      .flatMap {
        case (gameId, logFile) =>
          parseLogFile(gameId, "/*/*TechAILog_*.csv") {
          /*
           * Most lines have to do with evaluation and scoring logic; we are
           * only interested in technology research start and complete events
           */
          val logLines = logFile
            .split('\n')
            .filter(line => line.contains("CHOSEN") || line.contains("COMPLETED"))
            // Extract columns of interest
            .map(line => {
              val lineArr = line.split(',').map(s => s.trim)
              (gameId, lineArr(0).toInt, lineArr(1), lineArr(2), lineArr(3))
            })

          // Set up state for this players game technology progression
          var furthestGridx: Int = 0
          var currentTech: String = ""
          var currentTechStartTurn: Int = 0

          logLines.foldLeft(List[TechResearchInstance]()) {
            case (acc, (_, turn, _, "CHOSEN", tech)) =>
              currentTech = tech
              currentTechStartTurn = turn
              acc
            case (acc, (gameId, turn: Int, nation: String, "COMPLETED", tech)) =>
              if (TECH_TO_GRIDX_MAP(tech) > furthestGridx) furthestGridx = TECH_TO_GRIDX_MAP(tech)
              acc :+ (gameId, nation, tech, turn - currentTechStartTurn + 1, furthestGridx, currentTechStartTurn, turn)
          }
          }
    }
    .toDF("game_id", "nation", "tech", "duration", "gridx_at_start", "start_turn", "end_turn")

    researchDF.createOrReplaceTempView("research_instance")
    researchDF
  }
}
