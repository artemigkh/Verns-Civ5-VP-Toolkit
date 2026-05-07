package civ5

import org.apache.spark.sql.DataFrame
import SparkJob.spark.implicits._
import civ5.Constants.CIV_TAG_TO_TEXT_MAP
import org.apache.spark.SparkContext
import org.json4s._
import org.json4s.jackson.JsonMethods._

object MapState extends SparkJob {
  /**
   * Processes mapStateLog_Turn*.json files and returns a dataframe of plot information by
   * game_id, turn, and plot (x,y)
   *
   * Additionally, registers the dataframe under the Spark SQL temporary view "map_state"
   *
   * @param sc        - the spark context object
   * @param inputPath - base path of the logs
   * @return Spark Dataframe containing processed log rows
   */
  def ProcessMapStateLogs(
      sc: SparkContext,
      inputPath: String,
      gameIds: Option[Set[String]] = None
  ): DataFrame = {
    // Path-agnostic regex: works on POSIX and Windows file URIs once we
    // normalize backslashes to forward slashes.
    val gameIdAndTurnPattern = """.*/([^/]+)/mapStateLog_Turn(\d*).*""".r
    val effectiveMinParts = math.max(sc.defaultParallelism * 4, 8)
    val glob = gameIds match {
      case Some(ids) if ids.isEmpty =>
        // Return an empty DF with the right schema by using an unrestricted glob and a false filter.
        // (Cache helper short-circuits before reaching here in practice.)
        inputPath + "/__never_matches__/mapStateLog_Turn*.json.gz"
      case Some(ids) =>
        inputPath + "/{" + ids.toSeq.sorted.mkString(",") + "}/mapStateLog_Turn*.json.gz"
      case None =>
        inputPath + "/*/mapStateLog_Turn*.json.gz"
    }
    // Short-circuit when no files match the glob -- otherwise wholeTextFiles
    // would throw InvalidInputException at action time. Returns an empty DF
    // with the same schema as the populated path below.
    if (!Util.globMatchesAny(sc, glob)) {
      println(s"[skip] no files match glob: $glob")
      val emptyDF = SparkJob.spark.emptyDataset[(String, String, String, Int, Int, String, String, Int, Int)]
        .toDF("game_id", "owner_civ", "turn", "city_id", "route_type", "unit", "unit_owner_civ", "x", "y")
        .persist
      emptyDF.createOrReplaceTempView("map_state")
      return emptyDF
    }
    val mapStateDF = sc.wholeTextFiles(glob, effectiveMinParts)
      .filter { case (_, logFile) => logFile.nonEmpty }
      // Map file name to game ID
      .map {
        case (fileName, logFile) =>
          val gameIdAndTurnPattern(gameId, turn) = fileName.replace('\\', '/')
          (gameId, (turn.toInt + 1).toString, logFile, fileName)
      }
      .flatMap { case (gameId, turn, logFile, fileName) =>
        var jsonMap: Map[String, Any] = Map()
        try {
          jsonMap = parse(logFile.filter(_ >= ' ')).values.asInstanceOf[Map[String, Any]]
        } catch {
          case e: Exception => {
            println("crashed on this file contents")
            println(logFile)
            println("with file name")
            println(fileName)
          }
        }

        // Create mapping of player IDs to civ names
        val playerDataMap = jsonMap("MapData").asInstanceOf[Map[String, Any]]("Civ5PlayerData")
          .asInstanceOf[List[Map[String, Any]]]
          .map(pd => (pd("Index").asInstanceOf[BigInt].toInt, pd("CivType").asInstanceOf[String]))
          .filter(p => p._1 < 8)
          .map { case (index, civ) => index -> civ }
          .toMap

        jsonMap("MapData").asInstanceOf[Map[String, Any]]("MapTileImprovements")
          .asInstanceOf[List[Map[String, Any]]]
          .map(mti => {
            val plotOwner = mti("Owner").asInstanceOf[BigInt].toInt
            ( if (plotOwner >= 8) "" else CIV_TAG_TO_TEXT_MAP(playerDataMap(plotOwner)), mti)
          }
          )
          .map { case (owner, mti) =>
          val unitOwner = mti("UnitOwner").asInstanceOf[BigInt].toInt
          (
            gameId, owner, turn,
            mti("CityId").asInstanceOf[BigInt].toInt,
            mti("RouteType").asInstanceOf[BigInt].toInt,
            mti("Unit").asInstanceOf[String],
            if (unitOwner >= 8) "" else CIV_TAG_TO_TEXT_MAP(playerDataMap(unitOwner)),
            mti("X").asInstanceOf[BigInt].toInt,
            mti("Y").asInstanceOf[BigInt].toInt
          )}
      }
      .toDF("game_id", "owner_civ", "turn", "city_id", "route_type", "unit", "unit_owner_civ", "x", "y")
      .persist
    mapStateDF.createOrReplaceTempView("map_state")
    mapStateDF
  }

  /**
   * Aggregates the mapStateDF produced by ProcessMapStateLogs() to produce the following views:
   * - ownership_by_game_civ_turn: total owned counts by game_id, civ, turn
   * - ownership_by_game_turn: total owned counts by any player (used to calculate % of map)
   * - effective_ownership_by_game_turn: total owned counts by game_id, civ, turn taking into account master-vassal relations and percentages
   * Requires that the spark context contains view vassalage_deal
   *
   * @return
   */
  def AggregateMapStateRecords(mapStateDF: DataFrame) = {
    mapStateDF
      .rdd
      /*
       * Do a map-reduce style aggregation with (game_id, owner_civ, turn)
       * as the key to group by and (tiles_owned, cities_owned) as the value which
       * will be added element-wise as the reduce step
       */
      .map(row => {
        ((row(0).asInstanceOf[String], // game_id
          row(1).asInstanceOf[String], // owner_civ
          row(2).asInstanceOf[String] // turn
        ), (
          1, // tiles_owned
          if (row(3).asInstanceOf[Int] >= 0) 1 else 0 // cities_owned
        ))
      })
      .filter(row => row._1._2.nonEmpty) // Only use plots that have an owner
      .reduceByKey { case ((t1, c1), (t2, c2)) => (t1 + t2, c1 + c2) } // add values element-wise
      .map { case ((a, b, c), (d, e)) => (a, b, c, d, e) } // flatten
      .toDF(colNames = "game_id", "owner_civ", "turn", "tiles_owned", "cities_owned")
      .createOrReplaceTempView("ownership_by_game_civ_turn")

    mapStateDF
      .rdd // Do a map-reduce style aggregation like before but with (game_id, turn)
      .filter(row => row(1).asInstanceOf[String].nonEmpty) // Only use plots that have an owner
      .map(row => {
        ((row(0).asInstanceOf[String], // game_id
          row(2).asInstanceOf[String] // turn
        ), (
          1, // tiles_owned
          if (row(3).asInstanceOf[Int] >= 0) 1 else 0 // cities_owned
        ))
      })
      .reduceByKey { case ((t1, c1), (t2, c2)) => (t1 + t2, c1 + c2) }
      .map { case ((a, b), (c, d)) => (a, b, c, d) } // flatten
      .toDF(colNames = "game_id", "turn", "tiles_owned", "cities_owned")
      .createOrReplaceTempView("ownership_by_game_turn")

      spark.sql(
        """
          | WITH ownership_with_vassalage AS (
          | SELECT
          |   o.game_id,
          |   o.owner_civ,
          |   v.master,
          |   o.turn,
          |   o.tiles_owned,
          |   o.cities_owned,
          |   (CASE WHEN v.master IS NOT NULL THEN v.master ELSE o.owner_civ END) AS effective_owner
          | FROM
          |   ownership_by_game_civ_turn o LEFT JOIN vassalage_deal v
          | ON
          |   o.game_id = v.game_id AND
          |   o.owner_civ = v.vassal AND
          |   o.turn >= v.turn)
          | SELECT
          |   game_id,
          |   effective_owner,
          |   turn,
          |   SUM(tiles_owned) AS tiles_owned,
          |   SUM(cities_owned) AS cities_owned
          | FROM
          |   ownership_with_vassalage
          | GROUP BY
          |   game_id,
          |   effective_owner,
          |   turn
          |""".stripMargin).createOrReplaceTempView("effective_ownership_by_game_turn")

      spark.sql(
        """
          | SELECT
          |   eo.game_id,
          |   eo.effective_owner,
          |   eo.turn,
          |   eo.tiles_owned,
          |   eo.cities_owned,
          |   eo.tiles_owned / total.tiles_owned AS tiles_owned_percentage,
          |   eo.cities_owned / total.cities_owned AS cities_owned_percentage
          | FROM
          |   effective_ownership_by_game_turn eo LEFT JOIN ownership_by_game_turn total
          |     ON eo.game_id = total.game_id AND
          |        eo.turn = total.turn
          |""".stripMargin).createOrReplaceTempView("effective_ownership_by_game_turn")
  }

  def AggregateMapStateByEra(mapStateDF: DataFrame): DataFrame = {
    // Aggregate unit ownership using the same approach as tile ownership but without vassalage transfership
    mapStateDF
      .rdd
      /*
       * Do a map-reduce style aggregation with (game_id, owner_civ, turn)
       * as the key to group by and (units_owned) as the value which
       * will be added element-wise as the reduce step
       */
      .map(row => {
        ((row(0).asInstanceOf[String], // game_id
          row(6).asInstanceOf[String], // owner_civ
          row(2).asInstanceOf[String] // turn
        ),
          if (row(5).asInstanceOf[String].nonEmpty) 1 else 0
        )
      })
      .filter(row => row._1._2.nonEmpty) // Only use plots that have a unit owner
      .reduceByKey { _ + _ } // add values element-wise
      .map { case ((a, b, c), d) => (a, b, c, d) } // flatten
      .toDF(colNames = "game_id", "civ", "turn", "units_owned")
      .createOrReplaceTempView("unit_ownership_by_game_civ_turn")

    mapStateDF
      .rdd // Do a map-reduce style aggregation like before but with (game_id, turn)
      .filter(row => row(6).asInstanceOf[String].nonEmpty) // Only use plots that have an owner
      .map(row => {
        ((row(0).asInstanceOf[String], // game_id
          row(2).asInstanceOf[String] // turn
        ),
          if (row(5).asInstanceOf[String].nonEmpty) 1 else 0
        )
      })
      .reduceByKey { _ + _ }
      .map { case ((a, b), c) => (a, b, c) } // flatten
      .toDF(colNames = "game_id", "turn", "units_owned")
      .createOrReplaceTempView("unit_ownership_by_game_turn")

    spark.sql(
      """
        | SELECT
        |   uo.game_id,
        |   uo.civ,
        |   era,
        |   AVG(uo.units_owned / total.units_owned) AS units_owned_percentage_avg
        | FROM
        |   unit_ownership_by_game_civ_turn uo
        |   LEFT JOIN unit_ownership_by_game_turn total
        |     ON uo.game_id = total.game_id AND uo.turn = total.turn
        |   LEFT JOIN civ_turn_era e
        |     ON uo.game_id = total.game_id AND uo.turn = total.turn AND uo.civ = e.civ
        | GROUP BY
        |   uo.game_id,
        |   uo.civ,
        |   era
        | ORDER BY
        |   uo.game_id,
        |   uo.civ,
        |   era
        |""".stripMargin).createOrReplaceTempView("unit_ownership_by_era")

    spark.sql(
      """
        | SELECT
        |   eo.game_id,
        |   eo.effective_owner AS civ,
        |   era,
        |   AVG(tiles_owned_percentage) AS tiles_owned_percentage_avg,
        |   AVG(cities_owned_percentage) AS cities_owned_percentage_avg
        | FROM
        |   effective_ownership_by_game_turn eo, civ_turn_era e
        | WHERE
        |   eo.game_id = e.game_id AND
        |   eo.effective_owner = e.civ AND
        |   eo.turn = e.turn
        | GROUP BY
        |   eo.game_id,
        |   eo.effective_owner,
        |   era
        | ORDER BY
        |   eo.game_id,
        |   eo.effective_owner,
        |   era
        |""".stripMargin).createOrReplaceTempView("plot_ownership_by_era")


    val mapStateByEraDF = spark.sql(
      """
        | SELECT
        |   po.game_id,
        |   po.civ,
        |   po.era,
        |   tiles_owned_percentage_avg,
        |   cities_owned_percentage_avg,
        |   units_owned_percentage_avg
        | FROM plot_ownership_by_era po, unit_ownership_by_era uo
        | WHERE
        |   po.game_id = uo.game_id AND po.civ = uo.civ AND po.era = uo.era
        |""".stripMargin)
    mapStateByEraDF.createOrReplaceTempView("map_state_by_era")
    mapStateByEraDF
  }
}
