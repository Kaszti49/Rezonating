/*
 * Rezonating bench bring-up for the classic ESP32 rig (bench-only, not the node firmware).
 *
 * ADC 15 Click (ADS131M02 + LTC6903 clock) on SPI3, HX711 bit-banged. Prints a readable,
 * greppable report on UART0 at 115200. Every line starts with a tag:
 *   [BOOT] banner, [LTC] clock chip, [ADC] ADC identity/config, [RATE] measured data rate,
 *   [HX] HX711 detection, [STAT] once-per-second channel stats, [CNT] cumulative counters (10 s).
 *
 * Datasheet references:
 *   ADS131M02: TI SBAS853A (Jan 2020, rev. Apr 2021).
 *   LTC6903:   ADI/LT 69034fe, "Serial Port Register Description", Table 2, Table 3.
 */
#include <inttypes.h>
#include <math.h>
#include <stdbool.h>
#include <stdio.h>
#include <string.h>

#include "driver/gpio.h"
#include "driver/spi_master.h"
#include "esp_chip_info.h"
#include "esp_flash.h"
#include "esp_rom_sys.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/task.h"

/* ---------------------------------------------------------------- pin map (wired 2026-10-13) */
#define PIN_SCK      GPIO_NUM_18 /* Click SCK */
#define PIN_MISO     GPIO_NUM_19 /* Click SDO = ADC DOUT */
#define PIN_MOSI     GPIO_NUM_23 /* Click SDI = ADC DIN and LTC6903 SDI */
#define PIN_CS_ADC   GPIO_NUM_17 /* Click CS1 */
#define PIN_CS_LTC   GPIO_NUM_16 /* Click CS2 (mikroBUS PWM) = LTC6903 SEN */
#define PIN_DRDY     GPIO_NUM_4  /* Click INT = ADC DRDY, active low */
#define PIN_RST      GPIO_NUM_27 /* Click RST = ADC SYNC/RESET, active low */
#define PIN_HX_DT    GPIO_NUM_34 /* HX711 DT (input-only pin, no internal pulls) */
#define PIN_HX_SCK   GPIO_NUM_32 /* HX711 SCK */
#define SPI_HOST_ID  SPI3_HOST   /* GPIO 18/19/23 are the SPI3 (VSPI) IO_MUX pins */

#define LTC_SPI_HZ   1000000 /* LTC6903 fSCK max 20 MHz */
#define ADC_SPI_HZ   2000000 /* ADS131M02 is fine far above this; 2 MHz is kind to jumper wires */

/* ---------------------------------------------------------------- LTC6903 */
/* Word D15..D0 = OCT[3:0] DAC[9:0] CNF[1:0] (69034fe Table 3), MSB first, clocked in on SCK rising
 * edges while SEN is low (SPI mode 0). f = 2^OCT * 2078 Hz / (2 - DAC/1024).
 * OCT 12, DAC = round(2048 - 2078 * 2^(10+12) / 8.192 MHz) = round(984.06) = 984 -> 8.1915 MHz.
 * CNF 00 = CLK on and /CLK on (Table 2): which output the Click routes to CLKIN is not known, so both run. */
#define LTC_OCT      12u
#define LTC_DAC      984u
#define LTC_CNF      0u
#define LTC_WORD     ((uint16_t)((LTC_OCT << 12) | (LTC_DAC << 2) | LTC_CNF)) /* 0xCF60 */

/* ---------------------------------------------------------------- ADS131M02 (SBAS853A) */
#define ADC_CMD_NULL   0x0000u /* 8.5.1.10.1, response = STATUS */
#define ADC_CMD_RREG   0xA000u /* 8.5.1.10.7: 101a aaaa annn nnnn */
#define ADC_CMD_WREG   0x6000u /* 8.5.1.10.8: 011a aaaa annn nnnn, ack 010a aaaa ammm mmmm */
#define ADC_REG_ID     0x00u   /* 8.6.1, reset 22xxh: [15:12] 0010b, CHANCNT[11:8] = 0010b */
#define ADC_REG_STATUS 0x01u   /* 8.6.2, reset 0500h */
#define ADC_REG_MODE   0x02u   /* 8.6.3, reset 0510h */
#define ADC_REG_CLOCK  0x03u   /* 8.6.4, reset 030Eh */
#define ADC_REG_GAIN1  0x04u   /* 8.6.5, reset 0000h */

/* MODE (8.6.3, Table 8-16): REG_CRC_EN 0, RX_CRC_EN 0, CRC_TYPE 0 (CCITT), RESET 0 (write 0 clears the
 * STATUS RESET flag), WLENGTH 01b (24 bit), TIMEOUT 1, DRDY_SEL 00b (most lagging), DRDY_HiZ 0 (driven
 * high), DRDY_FMT 0 (level: low until data are read). */
#define ADC_MODE_VAL   0x0110u
/* CLOCK (8.6.4, Table 8-17): CH1_EN 1, CH0_EN 1, TBM 0, OSR 100b = 2048, PWR 10b = high-resolution.
 * fDATA = fMOD / OSR = (fCLKIN / 2) / OSR (8.3.7, Eq. 5) = 4.096 MHz / 2048 = 2000 SPS. */
#define ADC_OSR        2048u
#define ADC_CLOCK_VAL  0x0312u
/* GAIN1 (8.6.5, Table 8-18): PGAGAIN1[6:4] = 111b, PGAGAIN0[2:0] = 111b -> gain 128 on both. */
#define ADC_GAIN       128
#define ADC_GAIN1_VAL  0x0077u

#define ADC_NOMINAL_SPS 2000.0
#define ADC_WORD_BYTES  3                       /* 24-bit words (WLENGTH 01b) */
#define ADC_FRAME_BYTES (4 * ADC_WORD_BYTES)    /* response, ch0, ch1, CRC (8.5.1.7) */
#define ADC_CODE_MAX    0x7FFFFF                /* + full scale (8.5.1.9) */
#define ADC_CODE_MIN    (-0x800000)             /* - full scale */
#define ADC_LSB_UV      (1.2e6 / ADC_GAIN / 8388608.0) /* +-1.2 V / gain over 2^23 codes */

#define RATE_WINDOW_S   10

/* ---------------------------------------------------------------- shared state */
typedef struct {
    uint16_t resp;
    int32_t ch[2];
    uint16_t crc_rx;
    uint16_t crc_calc;
} adc_frame_t;

typedef struct {
    /* this 1 s window */
    uint32_t n;
    int32_t ref[2]; /* first sample of the window: sums are taken relative to it (no cancellation) */
    int64_t sum[2];
    int64_t sumsq[2];
    int32_t min[2];
    int32_t max[2];
    uint32_t clip[2];
    uint32_t lost; /* missed DRDY + failed SPI reads in this window */
    uint32_t edges;
    int64_t t_us;  /* window length */
    /* cumulative totals since streaming started (64-bit sample counters) */
    uint64_t tot_edges;
    uint64_t tot_frames;
    uint64_t tot_missed;   /* DRDY edges whose data were never read (reader was late) */
    uint64_t tot_spi_err;  /* spi_device_polling_transmit failed: sample lost */
    uint64_t tot_crc_err;  /* output CRC mismatch: sample kept but suspect */
    uint64_t tot_no_flag;  /* STATUS had DRDY0/DRDY1 clear: data may be stale */
    uint64_t tot_timeouts; /* no DRDY for 100 ms */
    uint64_t tot_dev_reset;/* STATUS RESET bit came back: the ADC reset itself */
    uint32_t report_drops; /* windows not delivered to the printer (stats only, not samples) */
} win_stats_t;

typedef struct {
    bool present;
    uint32_t sps_guess;
    int32_t last;
    int64_t sum;    /* this report window */
    uint32_t n;     /* this report window */
    uint64_t reads; /* cumulative good reads */
    uint64_t bad;   /* DT not high after the 25th pulse: read discarded */
    uint64_t timeouts;
} hx_state_t;

static spi_device_handle_t s_ltc;
static spi_device_handle_t s_adc;
static TaskHandle_t s_adc_task;
static TaskHandle_t s_main_task;
static QueueHandle_t s_stat_q;
static volatile uint32_t s_drdy_edges; /* written only by the ISR */
static volatile bool s_report_on;
static hx_state_t s_hx;
static portMUX_TYPE s_hx_mux = portMUX_INITIALIZER_UNLOCKED;
static portMUX_TYPE s_hx_bitbang_mux = portMUX_INITIALIZER_UNLOCKED;

/* ---------------------------------------------------------------- helpers */
static const char *fmt_fixed(char *buf, size_t len, double v, int decimals)
{
    static const int64_t p10[] = {1, 10, 100, 1000, 10000, 100000};
    if (decimals < 0) {
        decimals = 0;
    }
    if (decimals > 5) {
        decimals = 5;
    }
    int64_t scaled = (int64_t)llround(fabs(v) * (double)p10[decimals]);
    if (decimals == 0) {
        snprintf(buf, len, "%c%" PRId64, v < 0 ? '-' : '+', scaled);
    } else {
        snprintf(buf, len, "%c%" PRId64 ".%0*" PRId64, v < 0 ? '-' : '+', scaled / p10[decimals], decimals,
                 scaled % p10[decimals]);
    }
    return buf;
}

/* CRC-16-CCITT, polynomial 0x1021, seed 0xFFFF (SBAS853A 8.3.12, Table 8-7). */
static uint16_t crc16_ccitt(const uint8_t *data, size_t len)
{
    uint16_t crc = 0xFFFF;
    for (size_t i = 0; i < len; i++) {
        crc ^= (uint16_t)data[i] << 8;
        for (int b = 0; b < 8; b++) {
            crc = (crc & 0x8000) ? (uint16_t)((crc << 1) ^ 0x1021) : (uint16_t)(crc << 1);
        }
    }
    return crc;
}

static int32_t sext24(const uint8_t *p)
{
    int32_t v = ((int32_t)p[0] << 16) | ((int32_t)p[1] << 8) | p[2];
    if (v & 0x800000) {
        v -= 0x1000000;
    }
    return v;
}

/* ---------------------------------------------------------------- LTC6903 */
static esp_err_t ltc_write(uint16_t word)
{
    uint8_t tx[2] = {(uint8_t)(word >> 8), (uint8_t)(word & 0xFF)};
    spi_transaction_t t = {.length = 16, .tx_buffer = tx};
    return spi_device_polling_transmit(s_ltc, &t);
}

/* ---------------------------------------------------------------- ADS131M02 */
/* One full frame (4 words, 8.5.1.7): DIN = cmd, data (or zero), 0, 0; DOUT = response to the previous
 * frame's command, ch0, ch1, CRC. The CRC covers every preceding output word including pad bits (8.3.12). */
static esp_err_t adc_frame(uint16_t cmd, uint16_t data, adc_frame_t *f)
{
    uint8_t tx[ADC_FRAME_BYTES] = {0};
    uint8_t rx[ADC_FRAME_BYTES] = {0};
    tx[0] = (uint8_t)(cmd >> 8);
    tx[1] = (uint8_t)(cmd & 0xFF);
    tx[3] = (uint8_t)(data >> 8);
    tx[4] = (uint8_t)(data & 0xFF);
    spi_transaction_t t = {.length = ADC_FRAME_BYTES * 8, .tx_buffer = tx, .rx_buffer = rx};
    esp_err_t err = spi_device_polling_transmit(s_adc, &t);
    if (err != ESP_OK) {
        return err;
    }
    f->resp = (uint16_t)((rx[0] << 8) | rx[1]);
    f->ch[0] = sext24(&rx[3]);
    f->ch[1] = sext24(&rx[6]);
    f->crc_rx = (uint16_t)((rx[9] << 8) | rx[10]);
    f->crc_calc = crc16_ccitt(rx, 3 * ADC_WORD_BYTES);
    return ESP_OK;
}

static esp_err_t adc_rreg(uint8_t addr, uint16_t *val)
{
    adc_frame_t f;
    esp_err_t err = adc_frame((uint16_t)(ADC_CMD_RREG | ((uint16_t)addr << 7)), 0, &f);
    if (err == ESP_OK) {
        err = adc_frame(ADC_CMD_NULL, 0, &f); /* single-register read: value is the next response (8.5.1.10.7.1) */
    }
    *val = (err == ESP_OK) ? f.resp : 0;
    return err;
}

static esp_err_t adc_wreg(uint8_t addr, uint16_t val, uint16_t *ack)
{
    adc_frame_t f;
    esp_err_t err = adc_frame((uint16_t)(ADC_CMD_WREG | ((uint16_t)addr << 7)), val, &f);
    if (err == ESP_OK) {
        err = adc_frame(ADC_CMD_NULL, 0, &f);
    }
    *ack = (err == ESP_OK) ? f.resp : 0;
    return err;
}

static void print_status(const char *tag, uint16_t st)
{
    printf("[ADC] %s 0x%04X: LOCK=%d F_RESYNC=%d REG_MAP=%d CRC_ERR=%d CRC_TYPE=%d RESET=%d WLENGTH=%d DRDY1=%d "
           "DRDY0=%d\n",
           tag, st, (st >> 15) & 1, (st >> 14) & 1, (st >> 13) & 1, (st >> 12) & 1, (st >> 11) & 1, (st >> 10) & 1,
           (st >> 8) & 3, (st >> 1) & 1, st & 1);
}

static void adc_write_check(const char *name, uint8_t addr, uint16_t val)
{
    uint16_t ack = 0;
    uint16_t back = 0;
    esp_err_t err = adc_wreg(addr, val, &ack);
    uint16_t want_ack = (uint16_t)(0x4000u | ((uint16_t)addr << 7)); /* 010a aaaa a000 0000: 1 register written */
    if (err == ESP_OK) {
        err = adc_rreg(addr, &back);
    }
    bool ok = err == ESP_OK && ack == want_ack && back == val;
    printf("[ADC] write %-6s (0x%02X) = 0x%04X  ack=0x%04X (want 0x%04X)  readback=0x%04X  %s%s\n", name, addr, val,
           ack, want_ack, back, ok ? "PASS" : "FAIL", err == ESP_OK ? "" : " (SPI error)");
}

static void IRAM_ATTR drdy_isr(void *arg)
{
    (void)arg;
    s_drdy_edges++;
    BaseType_t hp = pdFALSE;
    vTaskNotifyGiveFromISR(s_adc_task, &hp);
    if (hp == pdTRUE) {
        portYIELD_FROM_ISR();
    }
}

static void win_reset(win_stats_t *w)
{
    w->n = 0;
    w->lost = 0;
    w->edges = 0;
    for (int c = 0; c < 2; c++) {
        w->ref[c] = 0;
        w->sum[c] = 0;
        w->sumsq[c] = 0;
        w->min[c] = INT32_MAX;
        w->max[c] = INT32_MIN;
        w->clip[c] = 0;
    }
}

/* Pinned to core 1 together with the DRDY interrupt. Reads one frame per DRDY falling edge. */
static void adc_task(void *arg)
{
    (void)arg;
    win_stats_t w = {0};
    win_reset(&w);

    /* Data have not been read during configuration: the output FIFO holds two samples per channel. Read two
     * frames back to back to get in step with DRDY (SBAS853A 8.5.1.9.1). */
    adc_frame_t f;
    (void)adc_frame(ADC_CMD_NULL, 0, &f);
    (void)adc_frame(ADC_CMD_NULL, 0, &f);

    ESP_ERROR_CHECK(gpio_install_isr_service(0));
    gpio_config_t io = {
        .pin_bit_mask = 1ULL << PIN_DRDY,
        .mode = GPIO_MODE_INPUT,
        .pull_up_en = GPIO_PULLUP_ENABLE,
        .pull_down_en = GPIO_PULLDOWN_DISABLE,
        .intr_type = GPIO_INTR_NEGEDGE,
    };
    ESP_ERROR_CHECK(gpio_config(&io));
    ESP_ERROR_CHECK(gpio_isr_handler_add(PIN_DRDY, drdy_isr, NULL));

    uint32_t last_edges = s_drdy_edges;
    int64_t win_start = esp_timer_get_time();

    for (;;) {
        uint32_t pending = ulTaskNotifyTake(pdTRUE, pdMS_TO_TICKS(100));
        if (pending == 0) {
            w.tot_timeouts++;
        } else {
            if (pending > 1) {
                /* More than one DRDY since the last read: only the newest sample can still be read. */
                w.tot_missed += pending - 1;
                w.lost += pending - 1;
            }
            if (adc_frame(ADC_CMD_NULL, 0, &f) != ESP_OK) {
                w.tot_spi_err++;
                w.lost++;
            } else {
                w.tot_frames++;
                if (f.crc_rx != f.crc_calc) {
                    w.tot_crc_err++;
                }
                if ((f.resp & 0x0003) != 0x0003) {
                    w.tot_no_flag++;
                }
                if (f.resp & 0x0400) {
                    w.tot_dev_reset++;
                }
                if (w.n == 0) {
                    w.ref[0] = f.ch[0];
                    w.ref[1] = f.ch[1];
                }
                for (int c = 0; c < 2; c++) {
                    int32_t x = f.ch[c];
                    int64_t d = (int64_t)x - w.ref[c];
                    w.sum[c] += d;
                    w.sumsq[c] += d * d;
                    if (x < w.min[c]) {
                        w.min[c] = x;
                    }
                    if (x > w.max[c]) {
                        w.max[c] = x;
                    }
                    if (x >= ADC_CODE_MAX || x <= ADC_CODE_MIN) {
                        w.clip[c]++;
                    }
                }
                w.n++;
            }
        }

        int64_t now = esp_timer_get_time();
        if (now - win_start >= 1000000) {
            uint32_t e = s_drdy_edges;
            w.edges = e - last_edges; /* unsigned difference is wrap-safe */
            w.tot_edges += w.edges;
            last_edges = e;
            w.t_us = now - win_start;
            win_start = now;
            if (s_report_on && xQueueSend(s_stat_q, &w, 0) != pdTRUE) {
                w.report_drops++;
            }
            win_reset(&w);
        }
    }
}

/* ---------------------------------------------------------------- HX711 */
/* 24 bits MSB first, two's complement, then a 25th pulse (next conversion: channel A, gain 128).
 * SCK high for more than 60 us powers the HX711 down, so the pulses run with interrupts off on this core
 * (about 60 us in total). After the 25th pulse a real HX711 drives DT high until the next conversion. */
static bool hx_read(int32_t *out)
{
    uint32_t v = 0;
    portENTER_CRITICAL(&s_hx_bitbang_mux);
    for (int i = 0; i < 24; i++) {
        gpio_set_level(PIN_HX_SCK, 1);
        esp_rom_delay_us(1);
        v = (v << 1) | (uint32_t)gpio_get_level(PIN_HX_DT);
        gpio_set_level(PIN_HX_SCK, 0);
        esp_rom_delay_us(1);
    }
    gpio_set_level(PIN_HX_SCK, 1);
    esp_rom_delay_us(1);
    gpio_set_level(PIN_HX_SCK, 0);
    portEXIT_CRITICAL(&s_hx_bitbang_mux);
    esp_rom_delay_us(2);
    bool dt_high_after = gpio_get_level(PIN_HX_DT) == 1;
    int32_t s = (int32_t)v;
    if (s & 0x800000) {
        s -= 0x1000000;
    }
    *out = s;
    return dt_high_after;
}

/* Wait (polling every 1 ms) until DT goes low. Returns the time it went low, or -1 on timeout. */
static int64_t hx_wait_ready(int timeout_ms)
{
    for (int i = 0; i <= timeout_ms; i++) {
        if (gpio_get_level(PIN_HX_DT) == 0) {
            return esp_timer_get_time();
        }
        vTaskDelay(pdMS_TO_TICKS(1));
    }
    return -1;
}

static void hx_task(void *arg)
{
    (void)arg;
    const char *why = NULL;
    int32_t v = 0;
    int64_t t_ready[3] = {0};

    if (hx_wait_ready(1000) < 0) {
        why = "DT stayed high for 1 s (no HX711, not powered, or DT not on GPIO34)";
    } else {
        for (int i = 0; i < 3 && why == NULL; i++) {
            t_ready[i] = hx_wait_ready(300);
            if (t_ready[i] < 0) {
                why = "DT did not go low again within 300 ms";
            } else if (!hx_read(&v)) {
                why = "DT not high after the 25th SCK pulse (floating or stuck-low DT line)";
            }
        }
    }

    if (why != NULL) {
        printf("[HX] HX711 not found: %s. Carrying on without it.\n", why);
        xTaskNotifyGive(s_main_task);
        vTaskDelete(NULL);
        return;
    }

    uint32_t period_ms = (uint32_t)((t_ready[2] - t_ready[1]) / 1000);
    uint32_t sps = period_ms > 40 ? 10 : 80;
    taskENTER_CRITICAL(&s_hx_mux);
    s_hx.present = true;
    s_hx.sps_guess = sps;
    s_hx.last = v;
    taskEXIT_CRITICAL(&s_hx_mux);
    printf("[HX] HX711 found: conversion period %" PRIu32 " ms (about %" PRIu32 " SPS), first raw=%" PRId32
           " (channel A, gain 128)\n",
           period_ms, sps, v);
    xTaskNotifyGive(s_main_task);

    for (;;) {
        if (hx_wait_ready(1000) < 0) {
            taskENTER_CRITICAL(&s_hx_mux);
            s_hx.timeouts++;
            taskEXIT_CRITICAL(&s_hx_mux);
            continue;
        }
        bool ok = hx_read(&v);
        taskENTER_CRITICAL(&s_hx_mux);
        if (ok) {
            s_hx.last = v;
            s_hx.sum += v;
            s_hx.n++;
            s_hx.reads++;
        } else {
            s_hx.bad++;
        }
        taskEXIT_CRITICAL(&s_hx_mux);
    }
}

/* ---------------------------------------------------------------- report */
static void print_window(const win_stats_t *w, uint32_t sec)
{
    char a[24], b[24], c[24];
    printf("[STAT] t=%" PRIu32 "s n=%" PRIu32 " drdy=%" PRIu32 " lost=%" PRIu32, sec, w->n, w->edges, w->lost);
    for (int ch = 0; ch < 2; ch++) {
        if (w->n == 0) {
            printf(" | ch%d(screw CH%d) no samples", ch, ch + 1);
            continue;
        }
        double mean_d = (double)w->sum[ch] / w->n;            /* relative to ref */
        double var = (double)w->sumsq[ch] / w->n - mean_d * mean_d;
        if (var < 0) {
            var = 0;
        }
        double mean_code = (double)w->ref[ch] + mean_d;
        double ac_uv = sqrt(var) * ADC_LSB_UV;
        double rms_uv = sqrt(mean_code * mean_code + var) * ADC_LSB_UV;
        printf(" | ch%d(screw CH%d) mean=%suV rms=%suV ac_rms=%suV min=%" PRId32 " max=%" PRId32 " clip=%" PRIu32 "%s",
               ch, ch + 1, fmt_fixed(a, sizeof a, mean_code * ADC_LSB_UV, 3), fmt_fixed(b, sizeof b, rms_uv, 3),
               fmt_fixed(c, sizeof c, ac_uv, 4), w->min[ch], w->max[ch], w->clip[ch], w->clip[ch] ? " CLIPPING" : "");
    }

    hx_state_t hx;
    taskENTER_CRITICAL(&s_hx_mux);
    hx = s_hx;
    s_hx.sum = 0;
    s_hx.n = 0;
    taskEXIT_CRITICAL(&s_hx_mux);
    if (!hx.present) {
        printf(" | hx711 absent\n");
    } else if (hx.n == 0) {
        printf(" | hx711 n=0 last=%" PRId32 " (no new reading this second)\n", hx.last);
    } else {
        printf(" | hx711 n=%" PRIu32 " last=%" PRId32 " mean=%" PRId64 "\n", hx.n, hx.last, hx.sum / hx.n);
    }
}

static void print_counters(const win_stats_t *w)
{
    hx_state_t hx;
    taskENTER_CRITICAL(&s_hx_mux);
    hx = s_hx;
    taskEXIT_CRITICAL(&s_hx_mux);
    /* unaccounted = DRDY edges that are neither read, nor counted missed, nor a failed read. 0 or 1 (an edge
     * in flight at the window boundary) is normal; anything growing is a bug or a noisy DRDY line. */
    int64_t unacc = (int64_t)w->tot_edges - (int64_t)(w->tot_frames + w->tot_missed + w->tot_spi_err);
    printf("[CNT] drdy_edges=%" PRIu64 " frames=%" PRIu64 " missed=%" PRIu64 " spi_err=%" PRIu64 " crc_err=%" PRIu64
           " no_drdy_flag=%" PRIu64 " drdy_timeouts=%" PRIu64 " adc_resets=%" PRIu64 " unaccounted=%" PRId64
           " report_drops=%" PRIu32 " hx_reads=%" PRIu64 " hx_bad=%" PRIu64 " hx_timeouts=%" PRIu64 "\n",
           w->tot_edges, w->tot_frames, w->tot_missed, w->tot_spi_err, w->tot_crc_err, w->tot_no_flag,
           w->tot_timeouts, w->tot_dev_reset, unacc, w->report_drops, hx.reads, hx.bad, hx.timeouts);
}

/* ---------------------------------------------------------------- main */
void app_main(void)
{
    s_main_task = xTaskGetCurrentTaskHandle();

    /* 1. Banner */
    esp_chip_info_t chip;
    esp_chip_info(&chip);
    uint32_t flash_bytes = 0;
    (void)esp_flash_get_size(NULL, &flash_bytes);
    printf("\n[BOOT] Rezonating bench bring-up (bench-only, classic ESP32 + ADC 15 Click + HX711)\n");
    printf("[BOOT] chip model=%d (1=ESP32) rev=v%d.%d cores=%d flash=%" PRIu32 " MB IDF=%s\n", (int)chip.model,
           chip.revision / 100, chip.revision % 100, chip.cores, flash_bytes / (1024 * 1024), esp_get_idf_version());
    printf("[BOOT] pins: SCK=%d SDO/MISO=%d SDI/MOSI=%d CS1(ADC)=%d CS2(LTC6903)=%d DRDY=%d RST=%d | HX711 DT=%d SCK=%d\n",
           PIN_SCK, PIN_MISO, PIN_MOSI, PIN_CS_ADC, PIN_CS_LTC, PIN_DRDY, PIN_RST, PIN_HX_DT, PIN_HX_SCK);

    /* GPIO: RST high (idle), HX711 SCK low (powered), DT and DRDY inputs. */
    gpio_config_t out = {
        .pin_bit_mask = (1ULL << PIN_RST) | (1ULL << PIN_HX_SCK),
        .mode = GPIO_MODE_OUTPUT,
        .pull_up_en = GPIO_PULLUP_DISABLE,
        .pull_down_en = GPIO_PULLDOWN_DISABLE,
        .intr_type = GPIO_INTR_DISABLE,
    };
    gpio_set_level(PIN_RST, 1);
    gpio_set_level(PIN_HX_SCK, 0);
    ESP_ERROR_CHECK(gpio_config(&out));
    gpio_set_level(PIN_RST, 1);
    gpio_set_level(PIN_HX_SCK, 0);
    gpio_config_t in = {
        .pin_bit_mask = (1ULL << PIN_HX_DT) | (1ULL << PIN_DRDY),
        .mode = GPIO_MODE_INPUT,
        .pull_up_en = GPIO_PULLUP_DISABLE, /* GPIO34 has no pulls; DRDY gets its pull-up in adc_task */
        .pull_down_en = GPIO_PULLDOWN_DISABLE,
        .intr_type = GPIO_INTR_DISABLE,
    };
    ESP_ERROR_CHECK(gpio_config(&in));

    /* SPI3 with two devices: LTC6903 (mode 0) and ADS131M02 (mode 1). No DMA: frames are 2 and 12 bytes. */
    spi_bus_config_t bus = {
        .mosi_io_num = PIN_MOSI,
        .miso_io_num = PIN_MISO,
        .sclk_io_num = PIN_SCK,
        .quadwp_io_num = -1,
        .quadhd_io_num = -1,
        .data4_io_num = -1,
        .data5_io_num = -1,
        .data6_io_num = -1,
        .data7_io_num = -1,
        .max_transfer_sz = 64,
    };
    ESP_ERROR_CHECK(spi_bus_initialize(SPI_HOST_ID, &bus, SPI_DMA_DISABLED));
    spi_device_interface_config_t ltc_dev = {
        .mode = 0,
        .clock_speed_hz = LTC_SPI_HZ,
        .spics_io_num = PIN_CS_LTC,
        .queue_size = 1,
    };
    ESP_ERROR_CHECK(spi_bus_add_device(SPI_HOST_ID, &ltc_dev, &s_ltc));
    spi_device_interface_config_t adc_dev = {
        .mode = 1,
        .clock_speed_hz = ADC_SPI_HZ,
        .spics_io_num = PIN_CS_ADC,
        .queue_size = 1,
    };
    ESP_ERROR_CHECK(spi_bus_add_device(SPI_HOST_ID, &adc_dev, &s_adc));

    /* 2. LTC6903 to 8.192 MHz (must run before the ADC answers) */
    double f_ltc = (double)(1u << LTC_OCT) * 2078.0 / (2.0 - (double)LTC_DAC / 1024.0);
    esp_err_t err = ltc_write(LTC_WORD);
    char fb[24], fb2[24];
    printf("[LTC] word=0x%04X (OCT=%u DAC=%u CNF=%u) -> nominal %s Hz (%s ppm vs 8.192 MHz); write %s\n", LTC_WORD,
           LTC_OCT, LTC_DAC, LTC_CNF, fmt_fixed(fb, sizeof fb, f_ltc, 0),
           fmt_fixed(fb2, sizeof fb2, (f_ltc / 8192000.0 - 1.0) * 1e6, 0), err == ESP_OK ? "OK" : "FAILED");
    printf("[LTC] write-only chip: the clock is confirmed by the ADC answering and by [RATE] below\n");
    vTaskDelay(pdMS_TO_TICKS(20));

    /* 3. Reset the ADC: SYNC/RESET low > tw(RSL) = 2048 tCLKIN (250 us at 8.192 MHz) (SBAS853A 8.4.1.2) */
    gpio_set_level(PIN_RST, 0);
    vTaskDelay(pdMS_TO_TICKS(2));
    gpio_set_level(PIN_RST, 1);
    vTaskDelay(pdMS_TO_TICKS(10));
    printf("[ADC] RST pulsed (2 ms low). DRDY level now=%d\n", gpio_get_level(PIN_DRDY));

    adc_frame_t f;
    err = adc_frame(ADC_CMD_NULL, 0, &f);
    printf("[ADC] first frame after reset: response=0x%04X%s\n", f.resp, err == ESP_OK ? "" : " (SPI error)");
    uint16_t id = 0;
    uint16_t status = 0;
    (void)adc_rreg(ADC_REG_ID, &id);
    (void)adc_rreg(ADC_REG_STATUS, &status);
    unsigned chancnt = (id >> 8) & 0x0F;
    bool id_ok = ((id >> 12) & 0x0F) == 0x2 && chancnt == 2;
    if (id_ok) {
        printf("[ADC] ID=0x%04X -> ADS131M02, CHANCNT=2  PASS\n", id);
    } else {
        printf("[ADC] ID=0x%04X -> expected 0x22xx (ADS131M02, CHANCNT=2)  FAIL%s\n", id,
               (id == 0x0000 || id == 0xFFFF) ? " (all zeros/ones: no answer: check CLKIN/LTC6903, CS1, SDO, 3V3, GND)"
               : chancnt == 4             ? " (CHANCNT=4: this is an ADS131M04)"
                                          : "");
    }
    print_status("STATUS after reset", status);

    /* 4. Configure: 24-bit words, DRDY level output, 2 kSPS high-resolution, gain 128 on both channels */
    adc_write_check("MODE", ADC_REG_MODE, ADC_MODE_VAL);
    adc_write_check("GAIN1", ADC_REG_GAIN1, ADC_GAIN1_VAL);
    adc_write_check("CLOCK", ADC_REG_CLOCK, ADC_CLOCK_VAL);
    (void)adc_rreg(ADC_REG_STATUS, &status);
    print_status("STATUS after config", status);
    printf("[ADC] config: OSR=%u HR mode -> nominal 2000 SPS at 8.192 MHz; gain=%d on ch0 and ch1; full scale "
           "+-%s uV; 1 LSB=%s uV; 24-bit words\n",
           ADC_OSR, ADC_GAIN, fmt_fixed(fb, sizeof fb, 1.2e6 / ADC_GAIN, 3),
           fmt_fixed(fb2, sizeof fb2, ADC_LSB_UV, 5));

    /* Start the reader on core 1 (the DRDY ISR is installed from there). */
    s_stat_q = xQueueCreate(4, sizeof(win_stats_t));
    xTaskCreatePinnedToCore(adc_task, "adc", 4096, NULL, 10, &s_adc_task, 1);

    /* 5. Measure the real data rate: DRDY falling edges over 10 s against esp_timer */
    vTaskDelay(pdMS_TO_TICKS(1000));
    uint32_t e0 = s_drdy_edges;
    int64_t t0 = esp_timer_get_time();
    printf("[RATE] counting DRDY falling edges for %d s ...\n", RATE_WINDOW_S);
    vTaskDelay(pdMS_TO_TICKS(RATE_WINDOW_S * 1000));
    uint32_t e1 = s_drdy_edges;
    int64_t t1 = esp_timer_get_time();
    double hz = (double)(e1 - e0) * 1e6 / (double)(t1 - t0);
    char hb[24], pb[24], cb[24];
    printf("[RATE] edges=%" PRIu32 " in %" PRId64 " us -> measured %s Hz, nominal %d Hz, %s %% off; implied CLKIN "
           "%s Hz\n",
           e1 - e0, t1 - t0, fmt_fixed(hb, sizeof hb, hz, 3), (int)ADC_NOMINAL_SPS,
           fmt_fixed(pb, sizeof pb, (hz / ADC_NOMINAL_SPS - 1.0) * 100.0, 3),
           fmt_fixed(cb, sizeof cb, hz * 2.0 * ADC_OSR, 0));
    if (e1 == e0) {
        printf("[RATE] FAIL: no DRDY edges. Check INT->GPIO%d, CLKIN (LTC6903 on CS2), and the ADC ID above\n",
               PIN_DRDY);
    }

    /* 7. HX711: detect, then keep reading in the background */
    xTaskCreatePinnedToCore(hx_task, "hx711", 3072, NULL, 5, NULL, 0);
    (void)ulTaskNotifyTake(pdTRUE, pdMS_TO_TICKS(3000));

    /* 6 and 8. Once per second: channel stats, HX711, lost samples; counters every 10 s */
    printf("[STAT] columns: mean/rms/ac_rms input-referred uV at gain %d; min/max raw codes; clip = codes at full "
           "scale; lost = missed DRDY + failed reads this second\n",
           ADC_GAIN);
    s_report_on = true;
    uint32_t sec = 0;
    win_stats_t w;
    for (;;) {
        if (xQueueReceive(s_stat_q, &w, pdMS_TO_TICKS(2000)) != pdTRUE) {
            printf("[STAT] no stats from the ADC task for 2 s\n");
            continue;
        }
        sec++;
        print_window(&w, sec);
        if (sec % 10 == 0) {
            print_counters(&w);
        }
    }
}
