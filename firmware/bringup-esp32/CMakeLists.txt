# Bench-only bring-up for the classic ESP32 rig (ADC 15 Click + HX711). Not the node firmware.
cmake_minimum_required(VERSION 3.16)

include($ENV{IDF_PATH}/tools/cmake/project.cmake)
project(rezonating-bringup-esp32)
