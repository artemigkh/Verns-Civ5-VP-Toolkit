package civ5

import java.io.{File, FileWriter, PrintWriter}
import java.nio.file.{Files, Paths}
import java.time.LocalDateTime
import java.time.format.DateTimeFormatter

import org.apache.spark.sql.DataFrame

/**
 * Lightweight per-step perf tracker. Appends one CSV row per timed block to
 * `logs_processing/perf_metrics.csv` (gitignored). Captures wall-clock time,
 * input dataset size (set once per run), and optional output row count.
 *
 * Designed to be a no-op-friendly drop-in: failures writing the CSV are
 * swallowed so they never break the pipeline.
 */
object PerfTracker {
  private val tsFmt = DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss")
  private val Header =
    "timestamp,modpack_ver,step,input_files,input_bytes_mb,output_rows,duration_sec\n"

  @volatile private var modpackVer: String = "unknown"
  @volatile private var inputFiles: Long = -1L
  @volatile private var inputBytesMb: Double = -1.0
  @volatile private var csvPath: String = "perf_metrics.csv"
  @volatile private var runTimestamp: String = LocalDateTime.now().format(tsFmt)

  def configure(csv: String, modpack: String, inputPath: String): Unit = {
    csvPath = csv
    modpackVer = modpack
    runTimestamp = LocalDateTime.now().format(tsFmt)
    val (n, bytes) = scanInput(inputPath)
    inputFiles = n
    inputBytesMb = bytes / (1024.0 * 1024.0)
    ensureHeader()
  }

  private def scanInput(inputPath: String): (Long, Long) = {
    val root = new File(inputPath)
    if (!root.exists()) return (0L, 0L)
    var n = 0L
    var bytes = 0L
    val stack = scala.collection.mutable.Stack[File](root)
    while (stack.nonEmpty) {
      val f = stack.pop()
      if (f.isDirectory) {
        val children = f.listFiles()
        if (children != null) children.foreach(stack.push)
      } else {
        n += 1
        bytes += f.length()
      }
    }
    (n, bytes)
  }

  private def ensureHeader(): Unit = {
    try {
      val p = Paths.get(csvPath)
      if (!Files.exists(p)) {
        if (p.getParent != null) Files.createDirectories(p.getParent)
        val w = new PrintWriter(new FileWriter(p.toFile, false))
        try w.write(Header) finally w.close()
      }
    } catch { case _: Throwable => /* best effort */ }
  }

  private def append(step: String, outputRows: Long, durationSec: Double): Unit = {
    try {
      val w = new PrintWriter(new FileWriter(csvPath, true))
      try {
        w.write(
          s"$runTimestamp,$modpackVer,${csvEsc(step)},$inputFiles,${"%.2f".format(inputBytesMb)},$outputRows,${"%.3f".format(durationSec)}\n"
        )
      } finally w.close()
    } catch { case _: Throwable => /* best effort */ }
  }

  private def csvEsc(s: String): String =
    if (s.contains(',') || s.contains('"')) "\"" + s.replace("\"", "\"\"") + "\"" else s

  /** Time a block whose result we don't introspect for row count. */
  def time[T](step: String)(body: => T): T = {
    val t0 = System.nanoTime()
    val res = body
    val secs = (System.nanoTime() - t0) / 1e9
    println(s"[perf] $step took ${"%.2f".format(secs)}s")
    append(step, -1L, secs)
    res
  }

  /** Time a block returning a DataFrame; counts its rows AFTER the block returns. */
  def timeDF(step: String)(body: => DataFrame): DataFrame = {
    val t0 = System.nanoTime()
    val df = body
    val secs = (System.nanoTime() - t0) / 1e9
    println(s"[perf] $step took ${"%.2f".format(secs)}s")
    append(step, -1L, secs)
    df
  }

  /** Like timeDF but ALSO forces a count (useful when you want to materialize+measure rows). */
  def timeDFWithCount(step: String)(body: => DataFrame): (DataFrame, Long) = {
    val t0 = System.nanoTime()
    val df = body
    val n = df.count()
    val secs = (System.nanoTime() - t0) / 1e9
    println(s"[perf] $step took ${"%.2f".format(secs)}s (rows=$n)")
    append(step, n, secs)
    (df, n)
  }
}
