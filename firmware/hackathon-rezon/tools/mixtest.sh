#!/bin/sh
# Synthetic tests: a walking recording is added on top of the fall recordings at several offsets and levels.
# Shows: falls found (expected 3 and 4), extra fall alarms, and how often walking cancelled a fall ("got-up").
cd "$(dirname "$0")/.."
U=../../data/raw/hackathon
R2=$U/geophone_2026-11-12T10-50-07.csv; R3=$U/geophone_2026-11-12T11-01-32.csv; R4=$U/geophone_2026-11-12T11-35-59.csv
echo "base        walking added          falls  expected  got-up  bystander  newstep  floor"
for base in $R2 $R3; do
  exp=3; [ "$base" = "$R3" ] && exp=4
  n=$(basename $base .csv | cut -c21-)
  line=$(./tools/replay.exe --quiet "$@" $base)
  echo "$line" | awk -v n=$n -v e=$exp '{for(i=1;i<=NF;i++){if($i=="fall-shaped")f=$(i+1);if($i=="got-up")g=$(i+1);if($i=="bystander")b=$(i+1);if($i=="newstep")s=$(i+1);if($i=="floor")fl=$(i+1)} printf "%-11s %-22s %5d  %8d  %6d  %9d  %7d  %5d\n",n,"none",f,e,g,b,s,fl}'
  for sc in 1 2; do for off in 0 5 10 15 20; do
    line=$(./tools/replay.exe --quiet "$@" --mix "$R4:0:40@$off*$sc" --mix "$R4:0:40@$((off+38))*$sc" $base)
    echo "$line" | awk -v n=$n -v e=$exp -v w="rec4 x$sc at ${off}s" '{for(i=1;i<=NF;i++){if($i=="fall-shaped")f=$(i+1);if($i=="got-up")g=$(i+1);if($i=="bystander")b=$(i+1);if($i=="newstep")s=$(i+1);if($i=="floor")fl=$(i+1)} printf "%-11s %-22s %5d  %8d  %6d  %9d  %7d  %5d\n",n,w,f,e,g,b,s,fl}'
  done; done
done
