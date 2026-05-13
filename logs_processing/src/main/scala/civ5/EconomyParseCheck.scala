package civ5

import java.io.{File, FileInputStream}
import java.util.zip.GZIPInputStream

import scala.io.Source
import scala.util.{Failure, Success, Try}

/**
 * Standalone parser harness that exercises the Economy.scala parsing logic
 * against on-disk *.csv.gz files WITHOUT requiring Spark / Hadoop / spark-submit.
 *
 * Why: when Economy parsing throws inside the full pipeline, the resulting
 * Spark stack trace only points at the offending gameId. Running through
 * spark-submit takes minutes and rebuilds 30+ DataFrames before reaching
 * Economy. This harness reads the same gzipped logs directly and runs the
 * exact same column-extraction code, so a bad file surfaces in seconds with
 * the line index and content responsible.
 *
 * Build:  mvn -q -DskipTests package
 * Run:
 *   java -cp target/civ5-1.0.jar civ5.EconomyParseCheck <input_path> [gameId ...]
 *
 *   <input_path> e.g. data/MP_AUTOPLAY_VP_5_2_3/unpacked/all
 *   If no gameIds are given, every immediate sub-directory is scanned.
 *
 * Exits 0 if all files parse cleanly, 1 otherwise.
 */
object EconomyParseCheck {

  /** Mirrors the parsing logic in Economy.ProcessEconomicCityMonitorLogs. */
  def parseEconomicCityMonitorLog(content: String): Int = {
    content.split('\n')
      .filterNot(s => s.contains("Turn,"))
      .filter(_.trim.nonEmpty)
      .map { line =>
        val lineArr = line.split(',').map(_.trim)
        (
          lineArr(0),                // civ
          lineArr(1).toInt,          // turn
          lineArr(2),                // city_name
          lineArr(3).toDouble,       // population
          lineArr(4).toDouble,       // food
          lineArr(5).toDouble,       // production
          lineArr(6).toDouble,       // science
          lineArr(7).toDouble,       // gold
          lineArr(8).toDouble,       // culture
          lineArr(9).toDouble,       // faith
          lineArr(10).toDouble,      // tourism
          lineArr(11).toDouble       // golden_age_points
        )
      }
      .length
  }

  /** Mirrors the parsing logic in Economy.ProcessEconomicMonitorLogs (per-civ). */
  def parseEconomicMonitorLog(content: String): Int = {
    content.split('\n')
      .filterNot(s => s.contains("Turn,"))
      .filter(_.trim.nonEmpty)
      .map { line =>
        val lineArr = line.split(',').map(_.trim)
        // Only touch the indices that the production parser actually uses;
        // they go up to 35 in ProcessEconomicMonitorLogs.
        val _ = (
          lineArr(0),
          lineArr(1).toInt,
          lineArr(2).toDouble,
          lineArr(35).toDouble
        )
        1
      }
      .sum
  }

  def readGz(file: File): String = {
    val in = new GZIPInputStream(new FileInputStream(file))
    try Source.fromInputStream(in, "UTF-8").mkString finally in.close()
  }

  def listGameIds(root: File): Seq[String] =
    Option(root.listFiles()).getOrElse(Array.empty)
      .filter(_.isDirectory)
      .map(_.getName)
      .toSeq
      .sorted

  def matching(dir: File, prefix: String): Seq[File] =
    Option(dir.listFiles()).getOrElse(Array.empty)
      .filter(f => f.isFile && f.getName.startsWith(prefix) && f.getName.endsWith(".csv.gz"))
      .toSeq
      .sortBy(_.getName)

  case class Failed(file: File, msg: String, line: Int = -1, lineText: String = "")

  def checkOne(file: File, parser: String => Int): Either[Failed, Int] = {
    val content = Try(readGz(file)) match {
      case Success(c) => c
      case Failure(e) => return Left(Failed(file, s"gunzip failed: ${e.getMessage}"))
    }
    // Try the bulk parse first (cheap, succeeds on most files).
    Try(parser(content)) match {
      case Success(n) => Right(n)
      case Failure(_) =>
        // Fall back to a per-line walk to point at the bad row.
        val lines = content.split('\n')
        var i = 0
        while (i < lines.length) {
          val l = lines(i)
          if (!l.contains("Turn,")) {
            Try(parser(l)) match {
              case Failure(e) =>
                return Left(Failed(file, e.toString, i, l))
              case _ =>
            }
          }
          i += 1
        }
        Left(Failed(file, "parse failed but no single line reproduced it"))
    }
  }

  def main(argv: Array[String]): Unit = {
    if (argv.isEmpty) {
      Console.err.println("usage: EconomyParseCheck <input_path> [gameId ...]")
      sys.exit(2)
    }
    val inputPath = new File(argv(0))
    if (!inputPath.isDirectory) {
      Console.err.println(s"not a directory: $inputPath")
      sys.exit(2)
    }
    val gameIds = if (argv.length > 1) argv.drop(1).toSeq else listGameIds(inputPath)

    val parsers: Seq[(String, String => Int)] = Seq(
      "EconomicCityMonitorLog_" -> parseEconomicCityMonitorLog _,
      "EconomicMonitorLog_"     -> parseEconomicMonitorLog _
    )

    var totalOk = 0
    var totalEmpty = 0
    val failures = scala.collection.mutable.ArrayBuffer.empty[Failed]

    for (gid <- gameIds) {
      val gdir = new File(inputPath, gid)
      if (!gdir.isDirectory) {
        println(s"[skip] $gid (not a directory)")
      } else {
        for ((prefix, parser) <- parsers; f <- matching(gdir, prefix)) {
          val sz = f.length()
          if (sz == 0L) {
            // Note: the on-disk file is .csv.gz; size 0 means the gz wrapper
            // itself is missing. (A valid empty gzip is still ~20 bytes.)
            totalEmpty += 1
            println(f"[empty]   $gid/${f.getName} (0 bytes)")
          } else {
            checkOne(f, parser) match {
              case Right(n) =>
                totalOk += 1
                if (n == 0) println(f"[zero]    $gid/${f.getName} -> 0 rows after filter")
              case Left(fail) =>
                failures += fail
                val locator = if (fail.line >= 0) s"line ${fail.line}: '${fail.lineText}'" else ""
                println(s"[FAIL]    $gid/${f.getName}: ${fail.msg} $locator")
            }
          }
        }
      }
    }

    println()
    println(s"summary: ok=$totalOk empty=$totalEmpty failed=${failures.size}")
    if (failures.nonEmpty) sys.exit(1)
  }
}
