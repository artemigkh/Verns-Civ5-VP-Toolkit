package civ5

import org.apache.spark.sql.SparkSession

trait SparkJob {
  // Don't hard-code .master(...) here — the actual master is configured by
  // the SparkContext built in ProcessCiv5Logs.main (driven by spark-submit
  // flags, e.g. local[*]). Hard-coding "local" silently caps parallelism
  // to 1 core when this trait's session is touched before the SparkContext
  // is created.
  val spark: SparkSession = SparkSession.builder.getOrCreate
}
object SparkJob extends SparkJob {}