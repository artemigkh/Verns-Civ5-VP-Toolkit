package civ5

import java.io.File

import org.apache.hadoop.fs.{FileSystem, Path}
import org.apache.spark.SparkContext
import org.apache.spark.rdd.RDD
import org.apache.spark.sql.{DataFrame, SaveMode, SparkSession}

import scala.util.control.NonFatal

object Util {
  /**
   * Reads gzipped log files via wholeTextFiles and emits (gameId, fileContents) tuples.
   *
   * If `gameIds` is provided and non-empty, restricts the input glob to just those
   * gameIds via Hadoop brace expansion (`{id1,id2,...}`). When the resulting glob
   * matches 0 files (common: not every game has every log type, e.g. wonders),
   * returns an empty RDD instead of letting Hadoop throw InvalidInputException
   * deep inside an action.
   *
   * @param minPartitions Hint passed to wholeTextFiles. Bigger = better parallelism
   *                      and smaller per-task closure size, at the cost of more
   *                      task scheduling overhead. 0 means "auto" (4 * defaultParallelism).
   */
  def getGameIdLogContentsRDD(
      sc: SparkContext,
      inputPath: String,
      logFilePattern: String,
      gameIds: Option[Set[String]] = None,
      minPartitions: Int = 0
  ): RDD[(String, String)] = {
    val gameIdPattern = """.*/([^/]+)/[^/]+""".r

    val effectiveMinParts =
      if (minPartitions > 0) minPartitions
      else math.max(sc.defaultParallelism * 4, 8)

    gameIds match {
      case Some(ids) if ids.isEmpty =>
        sc.emptyRDD[(String, String)]
      case _ =>
        val glob = gameIds match {
          case Some(ids) =>
            // logFilePattern is expected to start with "/*/..." where the leading
            // "*" matches the gameId directory. Replace that wildcard with an
            // explicit brace expansion so we only read files for the requested
            // gameIds. If for some reason the pattern doesn't have the leading
            // "/*", fall back to appending the brace expansion (preserves prior
            // behaviour, even if not ideal).
            val patternWithoutLeadingStar =
              if (logFilePattern.startsWith("/*/")) logFilePattern.substring(2)
              else "/" + logFilePattern.stripPrefix("/")
            inputPath + "/{" + ids.toSeq.sorted.mkString(",") + "}" + patternWithoutLeadingStar + ".gz"
          case None =>
            inputPath + logFilePattern + ".gz"
        }
        if (!globMatchesAny(sc, glob)) {
          println(s"[skip] no files match glob: $glob")
          sc.emptyRDD[(String, String)]
        } else {
          sc.wholeTextFiles(glob, effectiveMinParts)
            .map {
              case (fileName, logFile) =>
                val gameIdPattern(gameId) = fileName.replace('\\', '/')
                (gameId, logFile)
            }
        }
    }
  }

  /**
   * Eagerly checks whether a Hadoop glob matches at least one file, so we can
   * short-circuit before sc.wholeTextFiles tries (and fails) inside an action.
   */
  def globMatchesAny(sc: SparkContext, glob: String): Boolean = {
    try {
      val path = new Path(glob)
      val fs = path.getFileSystem(sc.hadoopConfiguration)
      val statuses = fs.globStatus(path)
      statuses != null && statuses.nonEmpty
    } catch {
      case NonFatal(_) => false
    }
  }

  /**
   * Wraps a per-file log parsing block with a contextual crash handler.
   *
   * If anything inside ``body`` throws (out-of-bounds index, ``toInt``
   * NumberFormatException, regex mismatch, etc.) the original exception is
   * re-raised wrapped in a RuntimeException whose message names the
   * ``gameId`` and the glob pattern of the file being processed — which is
   * usually enough to find the offending file on disk for inspection.
   */
  def parseLogFile[T](gameId: String, logFilePattern: String)(body: => T): T = {
    try body catch {
      case NonFatal(e) =>
        throw new RuntimeException(
          s"Error processing log file (gameId=$gameId, pattern=$logFilePattern): ${e.getMessage}",
          e
        )
    }
  }

  /**
   * Lists immediate sub-directory names under `inputPath`. Each sub-directory
   * is treated as one gameId.
   */
  def listGameIds(inputPath: String): Set[String] = {
    val root = new File(inputPath)
    if (!root.isDirectory) return Set.empty
    val children = root.listFiles()
    if (children == null) Set.empty
    else children.filter(_.isDirectory).map(_.getName).toSet
  }

  /**
   * Per-gameId disk cache for parsed log dataframes.
   *
   *   1. Lists gameIds already present in the parquet cache directory.
   *   2. Computes `missing = allGameIds - cached`.
   *   3. If `missing` is non-empty, runs `compute(missing)` to produce rows for
   *      ONLY those gameIds and appends them to the parquet cache (partitioned by game_id).
   *      If the resulting DF is empty (no log files of this type exist for any
   *      missing game), writes a marker so we don't re-attempt next run.
   *   4. Reads the full cache back and returns it (with original column order restored).
   */
  def cachedParse(
      spark: SparkSession,
      cacheRoot: String,
      name: String,
      allGameIds: Set[String]
  )(compute: Set[String] => DataFrame): DataFrame = {
    val dir = new File(cacheRoot, name)
    val cachedIds = listCachedGameIds(dir)
    val missing = allGameIds.diff(cachedIds)

    val columnsFile = new File(dir, "_columns.txt")
    val markerFile = new File(dir, "_no_data.marker")

    if (missing.nonEmpty) {
      println(s"[cache] $name: ${cachedIds.size} cached, ${missing.size} to parse")
      val freshDF = compute(missing)
      val originalCols = freshDF.columns.toSeq
      // Materialize with a count so we can decide if there are any rows to write.
      // (Empty DF -> partitionBy write produces 0 partitions and a directory with
      // only metadata, which is fine but let's be explicit.)
      val n = freshDF.count()
      if (n > 0) {
        freshDF.write
          .mode(SaveMode.Append)
          .partitionBy("game_id")
          .parquet(dir.getAbsolutePath)
      } else {
        // Make sure the cache dir exists with at least the schema sidecar so
        // subsequent runs see the dir as initialized.
        if (!dir.exists()) dir.mkdirs()
        // Emit an empty parquet with the right schema so spark.read.parquet works.
        if (!new File(dir, "_SUCCESS").isFile) {
          freshDF.write.mode(SaveMode.Overwrite).parquet(dir.getAbsolutePath)
        }
        new java.io.FileWriter(markerFile, false).close()
      }
      writeColumns(columnsFile, originalCols)
    } else {
      println(s"[cache] $name: full hit (${cachedIds.size} games)")
    }

    // Partition values like "2026-05-03T16.09.11.793785" get inferred as
    // Date/Timestamp by default, which then fails downstream code that
    // calls row.getString(0) on the game_id column. Disable inference so
    // partition columns are always read as strings.
    val priorInfer = spark.conf.getOption("spark.sql.sources.partitionColumnTypeInference.enabled")
    spark.conf.set("spark.sql.sources.partitionColumnTypeInference.enabled", "false")
    val readBack = try {
      spark.read.parquet(dir.getAbsolutePath)
    } finally {
      priorInfer match {
        case Some(v) => spark.conf.set("spark.sql.sources.partitionColumnTypeInference.enabled", v)
        case None => spark.conf.unset("spark.sql.sources.partitionColumnTypeInference.enabled")
      }
    }
    val originalCols = readColumns(columnsFile)
    if (originalCols.nonEmpty && originalCols.toSet == readBack.columns.toSet) {
      readBack.select(originalCols.head, originalCols.tail: _*)
    } else {
      readBack
    }
  }

  private def writeColumns(f: File, cols: Seq[String]): Unit = {
    try {
      val parent = f.getParentFile
      if (parent != null && !parent.exists()) parent.mkdirs()
      val w = new java.io.PrintWriter(new java.io.FileWriter(f, false))
      try cols.foreach(c => w.println(c)) finally w.close()
    } catch { case _: Throwable => /* best effort */ }
  }

  private def readColumns(f: File): Seq[String] = {
    if (!f.isFile) return Seq.empty
    try {
      val src = scala.io.Source.fromFile(f)
      try src.getLines().map(_.trim).filter(_.nonEmpty).toList
      finally src.close()
    } catch { case _: Throwable => Seq.empty }
  }

  /** Lists the gameIds already present in the cache by inspecting partition dirs. */
  def listCachedGameIds(cacheDir: File): Set[String] = {
    if (!cacheDir.isDirectory) return Set.empty
    val children = cacheDir.listFiles()
    if (children == null) return Set.empty
    val prefix = "game_id="
    children
      .filter(f => f.isDirectory && f.getName.startsWith(prefix))
      .map(_.getName.substring(prefix.length))
      .toSet
  }

  /** Recursively delete a directory (used by the --reset-cache flag). */
  def rmTree(dir: File): Unit = {
    if (!dir.exists()) return
    if (dir.isDirectory) {
      val children = dir.listFiles()
      if (children != null) children.foreach(rmTree)
    }
    dir.delete()
  }
}
