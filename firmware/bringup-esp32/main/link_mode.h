/*
 * Bench link mode: link protocol v0 (tools/lab/PROTOCOL.md) on UART0 at 115200, streaming adc_dec only.
 *
 * Text mode until a valid GET_INFO arrives on UART0; then all text stops for good (until reboot) and the link task
 * runs the USB session rules over the CP2102 UART. See README.md "Link mode".
 */
#pragma once

#include <stdbool.h>
#include <stdint.h>

/* First thing in app_main: text lock, UART0 driver (RX for GET_INFO), DATA queue and the link task (core 0). */
void link_init(void);

/* printf for the text report; prints nothing once link mode is on. Every text line goes through this. */
void link_txt(const char *fmt, ...) __attribute__((format(printf, 1, 2)));
bool link_mode_on(void);

/* ---- called from the ADC task only (core 1) ---- */

/* Once per loop iteration, before the edges of this wake-up: applies START/STOP requests from the link task. */
void link_adc_poll(void);

/* One DRDY sample interval while link acquisition runs: t_us = its DRDY ISR time, ok = false when the sample was lost
 * (missed DRDY, failed SPI read), ch = the two codes when ok. Runs the D-016 FIR; every second interval yields one
 * adc_dec index (sent, or counted in device_dropped). */
void link_adc_sample(int64_t t_us, bool ok, const int32_t *ch);

/* A GAIN1 register value to write (SET adc.gain.*): true with *reg and *gen when a write is pending. */
bool link_adc_gain_pending(uint16_t *reg, uint32_t *gen);
/* The ADC acknowledged (ok) or did not acknowledge the GAIN1 write of generation gen. */
void link_adc_gain_result(bool ok, uint32_t gen);
