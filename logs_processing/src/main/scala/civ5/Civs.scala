package civ5

import civ5.Util.getGameIdLogContentsRDD
import org.apache.spark.SparkContext
import org.apache.spark.sql.DataFrame
import org.apache.spark.sql.functions.when

import SparkJob.spark.implicits._

object Civs extends SparkJob {
  /**
   * Aggregates game records by civ to get a dataframe of average civ performance across all games
   *
   * Requires that the augmented_game_result view exists
   */
  def AggregateCivPerformance(): DataFrame = {
    val civPowerRankingDF = spark.sql(
      """
        | SELECT
        |   civ,
        |   COUNT(*) as count_games,
        |   AVG(CASE WHEN victory_type IS NULL THEN 0 ELSE 1 END) as winrate,
        |   SUM(culture_victory) AS culture_victories,
        |   SUM(diplomatic_victory) AS diplomatic_victories,
        |   SUM(domination_victory) AS domination_victories,
        |   SUM(science_victory) AS science_victories,
        |   SUM(time_victory) AS time_victories,
        |   AVG(culture_victory) as pct_culture_victories,
        |   AVG(diplomatic_victory) as pct_diplomatic_victories,
        |   AVG(domination_victory) as pct_domination_victories,
        |   AVG(science_victory) as pct_science_victories,
        |   AVG(time_victory) as pct_time_victories,
        |   AVG(tiles_owned_percentage) as avg_tiles_owned_percentage,
        |   AVG(cities_owned_percentage) as avg_cities_owned_percentage,
        |   AVG(score) AS avg_score
        | FROM augmented_game_result
        | GROUP BY civ
        |""".stripMargin)
    civPowerRankingDF.createOrReplaceTempView("power_ranking")
    civPowerRankingDF
  }

  /**
   * Aggregates policy and religion choices for every civ/game instance
   * Registers under view "civ_choices"
   *
   * @param policyChoiceDF Dataframe with civ policy choices
   * @param religionChoiceDF Dataframe with civ religion choices
   * @return
   */
  def AggregateCivChoices(policyChoiceDF: DataFrame, religionChoiceDF: DataFrame): DataFrame = {

    /*
    +--------------------+---------+-------------------+------------------+-------------------+----------------+--------------------+------------------+------------------+---------------------+---------------------+-------------------+-----------------+---------------------+
    |             game_id|      civ|e1_policy_tradition|e1_policy_progress|e1_policy_authority|e3_policy_fealty|e3_policy_statecraft|e3_policy_artistry|e5_policy_industry|e5_policy_imperialism|e5_policy_rationalism|e7_ideology_freedom|e7_ideology_order|e7_ideology_autocracy|
    +--------------------+---------+-------------------+------------------+-------------------+----------------+--------------------+------------------+------------------+---------------------+---------------------+-------------------+-----------------+---------------------+
    |2024-02-07T17.08....|   Sweden|                  0|                 0|                  1|               1|                   0|                 0|                 0|                    1|                    0|                  0|                0|                    1|
    |2024-02-08T00.06....| The Maya|                  1|                 0|                  0|               1|                   0|                 0|                 0|                    0|                    1|                  1|                0|                    0|
    |2024-02-07T22.16....| Portugal|                  1|                 0|                  0|               1|                   0|                 0|                 0|                    0|                    1|                  0|                0|                    0|
    |2024-02-07T17.52....|Byzantium|                  1|                 0|                  0|               0|                   1|                 0|                 0|                    0|                    1|                  1|                0|                    0|
    |2024-02-07T22.16....| The Maya|                  0|                 1|                  0|               1|                   0|                 0|                 0|                    0|                    1|                  0|                1|                    0|
     */
    policyChoiceDF
      .groupBy("game_id", "civ")
      .pivot("branch")
      .count().na.fill(0)
      .withColumnRenamed("0", "e1_policy_tradition")
      .withColumnRenamed("1", "e1_policy_progress")
      .withColumnRenamed("2", "e1_policy_authority")
      .withColumnRenamed("3", "e3_policy_fealty")
      .withColumnRenamed("4", "e3_policy_statecraft")
      .withColumnRenamed("5", "e3_policy_artistry")
      .withColumnRenamed("6", "e5_policy_industry")
      .withColumnRenamed("7", "e5_policy_imperialism")
      .withColumnRenamed("8", "e5_policy_rationalism")
      .withColumnRenamed("9", "e7_ideology_freedom")
      .withColumnRenamed("10", "e7_ideology_order")
      .withColumnRenamed("11", "e7_ideology_autocracy")
      .createOrReplaceTempView("civ_policy_choices_by_game")

    religionChoiceDF
      .filter(row => row.getAs[String]("type").equals("pantheon"))
      .select("game_id", "civ", "turn")
      .distinct()
      .createOrReplaceTempView("pantheon_founding_turn")

    religionChoiceDF
      .filter(row => row.getAs[String]("type").equals("religion_founded"))
      .select("game_id", "civ", "turn")
      .distinct()
      .createOrReplaceTempView("religion_founding_turn")

    religionChoiceDF
      .filter(row => row.getAs[String]("type").equals("religion_enhanced"))
      .select("game_id", "civ", "turn")
      .distinct()
      .createOrReplaceTempView("religion_enhancing_turn")

    religionChoiceDF
      .filter(row => row.getAs[String]("type").equals("religion_reformed"))
      .select("game_id", "civ", "turn")
      .distinct()
      .createOrReplaceTempView("religion_reformation_turn")

    val civChoicesDF = spark.sql(
      """
        | SELECT
        |   cg.game_id,
        |   cg.civ,
        |   pf.turn AS pantheon_founded,
        |   rf.turn AS religion_founded,
        |   re.turn AS religion_enhanced,
        |   rr.turn AS religion_reformed,
        |   p.e1_policy_tradition ,
        |   p.e1_policy_progress ,
        |   p.e1_policy_authority ,
        |   p.e3_policy_fealty ,
        |   p.e3_policy_statecraft ,
        |   p.e3_policy_artistry ,
        |   p.e5_policy_industry ,
        |   p.e5_policy_imperialism ,
        |   p.e5_policy_rationalism ,
        |   p.e7_ideology_freedom ,
        |   p.e7_ideology_order ,
        |   p.e7_ideology_autocracy
        | FROM
        |   civ_game_result cg
        | LEFT OUTER JOIN pantheon_founding_turn pf
        |   ON cg.game_id = pf.game_id AND cg.civ = pf.civ
        | LEFT OUTER JOIN religion_founding_turn rf
        |   ON cg.game_id = rf.game_id AND cg.civ = rf.civ
        | LEFT OUTER JOIN religion_enhancing_turn re
        |   ON cg.game_id = re.game_id AND cg.civ = re.civ
        | LEFT OUTER JOIN religion_reformation_turn rr
        |   ON cg.game_id = rr.game_id AND cg.civ = rr.civ
        | LEFT JOIN civ_policy_choices_by_game p
        |   ON cg.game_id = p.game_id AND cg.civ = p.civ
        |""".stripMargin)
    civChoicesDF.createOrReplaceTempView("civ_choices")
    civChoicesDF
  }
}
