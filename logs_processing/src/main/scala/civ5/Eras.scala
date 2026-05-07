package civ5

import org.apache.spark.sql.DataFrame
import SparkJob.spark.implicits._
import civ5.Constants.{GRIDX_TO_ERA_MAP, TECHS_AT_GRIDX_MAP, TECH_TO_GRIDX_MAP}

object Eras extends SparkJob {
  /**
   * Computes era from research instances by finding era transitions from either researching
   * a tech from the next era or all techs in the current era, then explodes each research instance
   * record to a row for every turn the civ is in that era
   *
   * @param researchDF : the research instance dataframe created by ProcessTechnologyLogs()
   * @return
   */
  def ComputeErasFromResearch(researchDF: DataFrame): DataFrame = {
    val eraDF = researchDF
      .groupByKey(row => (row.getString(0), row.getString(1)))
      .flatMapGroups {
        case ((gameId, nation), rows) =>
          // Handle each combination of gameId and nation here
          var currentEra = 1
          var techsDoneByGridX = List.range(0, 19).map(i => i -> 0).toMap

          rows.flatMap(row => {
            val tech = row.getString(2)
            val startTurn = row.getInt(5)
            val endTurn = row.getInt(6)
            val era = currentEra
            val technologyEra = GRIDX_TO_ERA_MAP(TECH_TO_GRIDX_MAP(tech))

            techsDoneByGridX = techsDoneByGridX.updated(technologyEra, techsDoneByGridX(TECH_TO_GRIDX_MAP(tech)) + 1)
            if (technologyEra > currentEra ||
              (techsDoneByGridX(TECH_TO_GRIDX_MAP(tech)) == TECHS_AT_GRIDX_MAP(technologyEra) &&
                List(2, 4, 6, 8, 10, 12, 14, 16, 17).contains(TECH_TO_GRIDX_MAP(tech)))
            ) {
              currentEra += 1
            }

            // For the duration of the research, every turn this civ is in the era it started in
            List.range(startTurn, endTurn + 1).map(turn => (gameId, nation, turn, era))
          })
      }
      .toDF("game_id", "civ", "turn", "era")
    eraDF.createOrReplaceTempView("civ_turn_era")
    eraDF
  }

  /**
   * Calculates the turns each civ/game instance reached each era.
   * Requires that view "civ_turn_era" exists
   * Registers result under view "era_transition_deltas"
   *
   * @return Dataframe with era transitions
   */
  def AggregateEraTransitionDeltas(): DataFrame = {
    spark.sql(
      """
        | SELECT
        |   game_id,
        |   civ,
        |   MIN(turn) as transition_turn,
        |   era
        | FROM civ_turn_era
        | GROUP BY game_id, civ, era
        |""".stripMargin).createOrReplaceTempView("era_transitions")

    // Aggregate average transition turn for each era by game
    spark.sql(
      """
        | SELECT
        |   game_id,
        |   era,
        |   AVG(transition_turn) AS avg_turn
        | FROM era_transitions
        | GROUP BY
        |   game_id,
        |   era
        |""".stripMargin).createOrReplaceTempView("era_transitions_by_game")

    val eraTransitionDeltasDF = spark.sql(
      """
        | SELECT
        |   et.game_id,
        |   et.civ,
        |   et.era,
        |   et.transition_turn - eg.avg_turn AS delta_turns
        | FROM era_transitions et
        | LEFT OUTER JOIN era_transitions_by_game eg
        | ON et.game_id = eg.game_id AND et.era = eg.era
        |""".stripMargin)
    eraTransitionDeltasDF.createOrReplaceTempView("era_transition_deltas")
    eraTransitionDeltasDF
  }
}
