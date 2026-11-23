/*
 * Which bench rig this build is for. The sources in this folder build two bench projects:
 *   firmware/bringup-esp32  classic ESP32 (WROOM-32) + ADC 15 Click + HX711; text report and link share UART0
 *                           (CP2102, 115200), link streams adc_dec only (adc_raw does not fit 115200 baud).
 *   firmware/rig-s3         ESP32-S3 DevKit + ADC 15 Click + two SM-24 geophones (OTIO wiring guide); text report on
 *                           UART0 (the board's UART/COM USB port), link on the native USB-Serial/JTAG port with
 *                           adc_raw (2 kSPS, D-020: what the Lab records) and adc_dec (1 kSPS, live view).
 * Pin maps are in bringup_main.c.
 */
#pragma once

#include "sdkconfig.h"

#if CONFIG_IDF_TARGET_ESP32S3
#define RIG_NAME          "ESP32-S3 rig (ADC 15 Click + 2 SM-24 geophones)"
#define RIG_LINK_USJ      1 /* link on USB-Serial/JTAG; the text report keeps running on UART0 */
#define RIG_HAS_RAW       1 /* adc_raw stream on the link */
#define RIG_HAS_HX711     0
/* Gain 4: +-300 mV full scale. On 2026-11-23 the floor-borne background on this rig peaked near 9 mV and direct
 * taps on a geophone at about 450 mV (gain 2), so 4 keeps everything but hard direct taps. SET adc.gain.0/1 changes
 * it per session; the Lab writes it into the sidecar. */
#define RIG_ADC_GAIN      4
#define RIG_ADC_GAIN_CODE 2u /* log2(RIG_ADC_GAIN), SBAS853A Table 8-18 */
#else
#define RIG_NAME          "classic ESP32 + ADC 15 Click + HX711"
#define RIG_LINK_USJ      0
#define RIG_HAS_RAW       0
#define RIG_HAS_HX711     1
#define RIG_ADC_GAIN      128 /* load cell: +-9.375 mV full scale */
#define RIG_ADC_GAIN_CODE 7u
#endif
