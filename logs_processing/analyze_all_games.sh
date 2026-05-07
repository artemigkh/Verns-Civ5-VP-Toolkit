#!/bin/bash

mvn clean package || exit
spark-submit --class civ5.ProcessCiv5Logs \
  --master local[*] \
  --driver-memory=12g \
  target/civ5-1.0.jar \
  --input /home/art/Data/civ5-4.21.1 \
  --output civ5-log-processor-output