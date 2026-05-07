package civ5

import org.apache.spark.SparkContext
import org.apache.spark.sql.DataFrame
import SparkJob.spark.implicits._
import org.apache.spark.sql.functions.input_file_name

object PlotYields extends SparkJob {
  /**
   * Processes BuilderTaskingYieldLog.csv files and returns a dataframe of plot yield rows,
   * one row per game_id, civ, turn, yield type/value combination
   *
   * Additionally, registers the dataframe under the Spark SQL temporary view "yields_from_plots_by_turn"
   *
   * @param sc        - the spark context object
   * @param inputPath - base path of the logs
   * @return Spark Dataframe containing processed log rows
   */
  def ProcessYieldLogs(sc: SparkContext, inputPath: String): DataFrame = {
    sc.textFile(inputPath + "/*/BuilderTaskingYieldLog.csv.gz")
      .filter(line => line.contains(",Plot Yield Update,"))
      .map(line => line.split(','))
      .filter(lineArr => lineArr.length >= 5)
      .map(lineArr => {
        (
          lineArr(0).trim, // civ
          lineArr(1).trim.toInt, // turn
          lineArr(3).trim, // yield
          lineArr(4).trim.toInt // amount
        )
      })
      .toDF("civ", "turn", "yield", "amount")
      .withColumn("INPUT_FILE", input_file_name())
      .createOrReplaceTempView("yields_from_plots_by_turn")

    val yieldsFromPlotsByTurnDF = spark.sql(
      """
        | SELECT
        |   SPLIT(INPUT_FILE, '/')[5] AS game_id,
        |   civ,
        |   turn,
        |   yield,
        |   SUM(amount) AS amount
        | FROM yields_from_plots_by_turn
        | GROUP BY
        |   game_id,
        |   civ,
        |   turn,
        |   yield
        | HAVING
        |   amount > 0
        |""".stripMargin)
    yieldsFromPlotsByTurnDF.createOrReplaceTempView("yields_from_plots_by_turn")
    yieldsFromPlotsByTurnDF
  }

  /**
   * Creates view plot_yields
   *
   * @param yieldsFromPlotsByTurnDF
   */
  def PivotPlotYieldsIntoColumns(yieldsFromPlotsByTurnDF: DataFrame) = {
    yieldsFromPlotsByTurnDF
      .groupBy("game_id", "civ", "turn")
      .pivot("yield")
      .sum("amount")
      .withColumnRenamed("YIELD_CULTURE", "p_culture")
      .withColumnRenamed("YIELD_FAITH", "p_faith")
      .withColumnRenamed("YIELD_FOOD", "p_food")
      .withColumnRenamed("YIELD_GOLD", "p_gold")
      .withColumnRenamed("YIELD_PRODUCTION", "p_production")
      .withColumnRenamed("YIELD_SCIENCE", "p_science")
      .createOrReplaceTempView("plot_yields")
  }
}
