package civ5

import org.apache.spark.SparkContext
import org.apache.spark.sql.DataFrame
import SparkJob.spark.implicits._
import civ5.Util.{getGameIdLogContentsRDD, parseLogFile}
import org.apache.spark.sql.functions.input_file_name

object City extends SparkJob {
  def ProcessCitySpecializationLogs(
      sc: SparkContext,
      inputPath: String,
      gameIds: Option[Set[String]] = None
  ): DataFrame = {
    val wondersDf = getGameIdLogContentsRDD(sc, inputPath, "/*/CitySpecializationLog_*.csv", gameIds)
      .flatMap {
        case (gameId, logFile) =>
          parseLogFile(gameId, "/*/CitySpecializationLog_*.csv") {
            logFile.split('\n')
              // Extract columns of interest
              .filter(line => line.contains(", WONDER - Finished"))
              .map(line => line.split(','))
              .map(lineArr => {
                (
                  gameId,
                  lineArr(1).trim, // civ
                  lineArr(0).trim.toInt, // turn
                  lineArr(5).trim.replace("WONDER - Finished ", "")
                )
              })
          }
      }
      .toDF("game_id", "civ", "turn", "wonder")

    wondersDf.createOrReplaceTempView("wonders_construction")
    wondersDf
  }
}