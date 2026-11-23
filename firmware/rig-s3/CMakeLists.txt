# Bench recording firmware for the ESP32-S3 rig (ADC 15 Click + two SM-24 geophones, OTIO wiring guide).
# Not the node firmware: it builds the bring-up sources in ../bringup-esp32/main for the ESP32-S3 (see rig.h there).
cmake_minimum_required(VERSION 3.16)

include($ENV{IDF_PATH}/tools/cmake/project.cmake)
project(rezonating-rig-s3)
