/*
 * Bench link mode (see link_mode.h, README.md "Link mode"). One link stream: adc_dec (id 1, 2 channels, 1000 Hz
 * nominal, D-016 63-tap FIR / 2, fir_delay 31). Session rules: PROTOCOL.md section 1, USB row, over UART0.
 *
 * Data path: the ADC task (core 1, priority 10) runs the FIR and fills 40-frame packets; a full packet goes into a
 * FreeRTOS queue with a zero timeout, so the ADC task never waits for the link. A packet that does not fit is counted
 * in win_link. The link task (core 0) is the only writer of UART0 in link mode: it answers commands (control frames go
 * out first), sends STATUS every status.period_ms and writes queued DATA while the UART TX ring holds less than
 * LINK_TX_HIGH bytes.
 */
#include "link_mode.h"

#include <inttypes.h>
#include <stdarg.h>
#include <stdio.h>
#include <string.h>

#include "driver/uart.h"
#include "esp_heap_caps.h"
#include "esp_log.h"
#include "esp_mac.h"
#include "esp_rom_sys.h"
#include "esp_system.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/semphr.h"
#include "freertos/task.h"
#include "rz_decim.h"
#include "rz_link.h"

#define LINK_UART       UART_NUM_0
#define LINK_RX_BUF     1024 /* driver RX ring: > SOC_UART_FIFO_LEN (128) */
#define LINK_TX_BUF     2048 /* driver TX ring */
#define LINK_TX_HIGH    512  /* queue DATA only while fewer bytes wait in the TX ring: control frames wait <= ~75 ms */
#define PKT_FRAMES      40   /* 1000 Hz / 40 = 25 DATA frames per second (PROTOCOL.md 4.3) */
#define DATA_Q_LEN      64   /* packets: 2.56 s at 25 per second, 22 kB internal RAM (no PSRAM on this board) */
#define STREAM_ID       1    /* adc_dec */
#define STREAM_MASK     (1u << STREAM_ID)
#define N_CH            2
#define LIVENESS_US     5000000
#define STOP_WAIT_MS    500  /* the ADC task polls requests at least every 100 ms (its DRDY timeout) */
#define GAIN_WAIT_MS    100
#define RATE_HIST       21   /* one point per 500 ms: 10 s */
#define RATE_STEP_US    500000
#define FW_VERSION      "bringup-0.2.0"
#define CODE_MAX        8388607
#define CODE_MIN        (-8388608)

#define REQ_START   1u
#define REQ_STOP    2u
#define REQ_DISCARD 4u /* with REQ_STOP: session end, the partial packet is not sent (counted in win_link) */

typedef struct {
    uint64_t first;
    int64_t t_us;
    uint16_t n;
    int32_t s[PKT_FRAMES][N_CH];
} dec_pkt_t;

/* Shared adc_dec stream state (PROTOCOL.md 4.4), guarded by s_mux. */
typedef struct {
    bool sending;
    bool acq_running;
    uint64_t produced;
    uint64_t device_dropped;
    uint64_t clipped;
    uint64_t win_first, win_end, win_device, win_link;
    int64_t last_t_us; /* DRDY time of the raw sample behind index produced - 1 */
} dec_state_t;

static portMUX_TYPE s_mux = portMUX_INITIALIZER_UNLOCKED;
static dec_state_t s_st;
static uint32_t s_req;           /* REQ_*, guarded by s_mux */
static uint8_t s_gain[N_CH] = {128, 128};
static uint32_t s_gain_gen;      /* bumped by SET adc.gain.*, guarded by s_mux */
static uint32_t s_gain_applied;  /* last generation the ADC acknowledged */
static uint32_t s_gain_fail;     /* GAIN1 writes the ADC did not acknowledge (retried) */
static SemaphoreHandle_t s_stop_done;
static QueueHandle_t s_data_q;

/* ADC task private */
static bool s_acq;
static rz_decim_t s_dec;
static dec_pkt_t s_pkt;

/* text gate */
static SemaphoreHandle_t s_txt_lock;
static volatile bool s_link_on;

/* link task private */
static bool s_live;
static uint16_t s_tx_seq;
static int64_t s_last_rx_us;
static int64_t s_next_status_us;
static uint16_t s_status_ms = 1000;
static char s_node_id[16];
static rzl_rx_t s_rx;
static uint8_t s_raw[1024];
static uint8_t s_wire[RZL_WIRE_LEN(sizeof s_raw)];
static struct {
    int64_t t;
    uint64_t p;
} s_rate[RATE_HIST];
static int s_rate_n;
static int64_t s_rate_next_us;
static uint32_t s_stop_timeouts; /* STOP whose drain the ADC task did not confirm in time */

/* ------------------------------------------------------------------ text gate */
void link_txt(const char *fmt, ...)
{
    if (s_link_on) {
        return;
    }
    if (s_txt_lock != NULL) {
        xSemaphoreTake(s_txt_lock, portMAX_DELAY);
    }
    if (!s_link_on) {
        va_list ap;
        va_start(ap, fmt);
        vprintf(fmt, ap);
        va_end(ap);
    }
    if (s_txt_lock != NULL) {
        xSemaphoreGive(s_txt_lock);
    }
}

bool link_mode_on(void) { return s_link_on; }

static int null_vprintf(const char *fmt, va_list ap)
{
    (void)fmt;
    (void)ap;
    return 0;
}

/* Text off for good: no line can start after this, the partial line in stdout goes out before the session's 0x00,
 * ESP_LOG is silenced and the ROM printf channels (esp_rom_printf, early and DRAM logs) are disconnected. */
static void enter_link_mode(void)
{
    xSemaphoreTake(s_txt_lock, portMAX_DELAY);
    s_link_on = true;
    fflush(stdout);
    xSemaphoreGive(s_txt_lock);
    esp_log_level_set("*", ESP_LOG_NONE);
    esp_log_set_vprintf(null_vprintf);
    esp_rom_install_channel_putc(1, NULL);
    esp_rom_install_channel_putc(2, NULL);
}

/* ------------------------------------------------------------------ ADC task side */
static void pkt_flush(bool discard)
{
    if (s_pkt.n == 0) {
        return;
    }
    if (discard || xQueueSend(s_data_q, &s_pkt, 0) != pdTRUE) {
        portENTER_CRITICAL(&s_mux);
        s_st.win_link += s_pkt.n; /* never handed to the transport */
        portEXIT_CRITICAL(&s_mux);
    }
    s_pkt.n = 0;
}

void link_adc_poll(void)
{
    portENTER_CRITICAL(&s_mux);
    uint32_t req = s_req;
    s_req = 0;
    if (req & REQ_START) {
        s_st.acq_running = true;
    }
    if (req & REQ_STOP) {
        if (s_st.sending) {
            s_st.win_end = s_st.produced; /* every index below it is computed: only the open packet is left */
            s_st.sending = false;
        }
        s_st.acq_running = false;
    }
    /* a STOP the link task gave up waiting for (stop_acquisition timeout): stop here, open packet not sent */
    bool orphan = s_acq && !(req & (REQ_START | REQ_STOP)) && !s_st.acq_running;
    portEXIT_CRITICAL(&s_mux);
    if (orphan) {
        pkt_flush(true);
        s_acq = false;
    }
    if (req & REQ_START) {
        rz_decim_init(&s_dec, N_CH); /* acquisition from idle: index 0 is the next DRDY, FIR history zeros */
        s_pkt.n = 0;
        s_acq = true;
    }
    if (req & REQ_STOP) {
        pkt_flush((req & REQ_DISCARD) != 0);
        s_acq = false;
        xSemaphoreGive(s_stop_done);
    }
}

void link_adc_sample(int64_t t_us, bool ok, const int32_t *ch)
{
    if (!s_acq) {
        return;
    }
    float y[N_CH];
    bool valid = false;
    if (!rz_decim_push(&s_dec, ch, ok, y, &valid)) {
        return; /* even raw index: no output */
    }
    uint64_t k = (s_dec.n_in - 2) / 2; /* output after raw sample 2k + 1 = n_in - 1 */
    int32_t c[N_CH];
    bool clip = false;
    for (int i = 0; i < N_CH; i++) {
        c[i] = rz_decim_code(y[i]);
        clip |= c[i] >= CODE_MAX || c[i] <= CODE_MIN;
    }
    portENTER_CRITICAL(&s_mux);
    s_st.produced = k + 1;
    s_st.last_t_us = t_us;
    bool sending = s_st.sending;
    if (!valid) {
        s_st.device_dropped++; /* a lost raw sample inside the FIR window: not sent */
        if (sending) {
            s_st.win_device++;
        }
    } else if (clip) {
        s_st.clipped++;
    }
    if (sending) {
        s_st.win_end = s_st.produced;
    }
    portEXIT_CRITICAL(&s_mux);
    if (!sending) {
        return;
    }
    if (!valid) {
        pkt_flush(false); /* a drop ends the packet; the next one starts after the gap */
        return;
    }
    if (s_pkt.n == 0) {
        s_pkt.first = k;
        s_pkt.t_us = t_us;
    }
    s_pkt.s[s_pkt.n][0] = c[0];
    s_pkt.s[s_pkt.n][1] = c[1];
    if (++s_pkt.n == PKT_FRAMES) {
        pkt_flush(false);
    }
}

static uint8_t gain_code(uint8_t g)
{
    uint8_t code = 0;
    while ((1u << code) < g) {
        code++;
    }
    return code;
}

bool link_adc_gain_pending(uint16_t *reg, uint32_t *gen)
{
    portENTER_CRITICAL(&s_mux);
    bool pending = s_gain_gen != s_gain_applied;
    /* GAIN1 (SBAS853A 8.6.5, Table 8-18): PGAGAIN1[6:4], PGAGAIN0[2:0], code = log2(gain) */
    *reg = (uint16_t)((gain_code(s_gain[1]) << 4) | gain_code(s_gain[0]));
    *gen = s_gain_gen;
    portEXIT_CRITICAL(&s_mux);
    return pending;
}

void link_adc_gain_result(bool ok, uint32_t gen)
{
    portENTER_CRITICAL(&s_mux);
    if (ok) {
        s_gain_applied = gen;
    } else {
        s_gain_fail++;
    }
    portEXIT_CRITICAL(&s_mux);
}

/* ------------------------------------------------------------------ link task: output */
static void uart_out(const uint8_t *b, size_t n) { uart_write_bytes(LINK_UART, b, n); }

/* Header, CRC, COBS; the seq is spent when the frame is written (PROTOCOL.md 2). Returns false if not all written. */
static bool send_frame(uint8_t type, const rzl_w_t *w)
{
    if (w->overflow) {
        return false;
    }
    size_t n = rzl_finish(s_raw, w->n, type, s_tx_seq, s_wire);
    s_tx_seq++;
    return uart_write_bytes(LINK_UART, s_wire, n) == (int)n;
}

static void send_ack(uint16_t cmd_seq)
{
    rzl_w_t w;
    rzl_payload_w(&w, s_raw, sizeof s_raw);
    rzl_enc_ack(&w, cmd_seq);
    send_frame(RZL_ACK, &w);
}

static void send_err(uint16_t cmd_seq, uint16_t code, const char *msg)
{
    rzl_w_t w;
    rzl_payload_w(&w, s_raw, sizeof s_raw);
    rzl_enc_err(&w, cmd_seq, code, msg);
    send_frame(RZL_ERR, &w);
}

static void send_hello_config(void)
{
    static const rzl_stream_info_t streams[] = {
        {STREAM_ID, N_CH, 1000, 24, 0 /* ltc6903 */, RZ_DECIM_TAPS, RZ_DECIM_DELAY},
    };
    s_tx_seq = 0; /* the node resets its seq at every HELLO */
    rzl_w_t w;
    rzl_payload_w(&w, s_raw, sizeof s_raw);
    rzl_enc_hello(&w, 0, FW_VERSION, s_node_id, (uint64_t)esp_timer_get_time(), streams, 1, NULL, 0);
    send_frame(RZL_HELLO, &w);

    uint8_t gain[N_CH];
    float scale[N_CH];
    static const uint8_t units[N_CH] = {1, 1}; /* V at the ADC input */
    portENTER_CRITICAL(&s_mux);
    memcpy(gain, s_gain, sizeof gain);
    portEXIT_CRITICAL(&s_mux);
    for (int i = 0; i < N_CH; i++) {
        scale[i] = (float)(1.2 / (double)gain[i] / 8388608.0); /* 1.2 V / gain / 2^23 */
    }
    rzl_stream_cfg_t cfg = {STREAM_ID, N_CH, gain, scale, units};
    rzl_payload_w(&w, s_raw, sizeof s_raw);
    rzl_enc_config(&w, &cfg, 1, 2 /* accel_range_g: no accel on this rig */, s_status_ms);
    send_frame(RZL_CONFIG, &w);
}

static uint32_t rate_mhz(void)
{
    if (s_rate_n < 2) {
        return 0;
    }
    int newest = s_rate_n - 1;
    int oldest = 0;
    while (oldest < newest - 1 && s_rate[newest].t - s_rate[oldest].t > 10000000) {
        oldest++;
    }
    int64_t dt = s_rate[newest].t - s_rate[oldest].t;
    if (dt < 200000) {
        return 0;
    }
    double r = (double)(s_rate[newest].p - s_rate[oldest].p) * 1e9 / (double)dt;
    return (uint32_t)(r + 0.5);
}

static void rate_sample(int64_t now)
{
    if (now < s_rate_next_us) {
        return;
    }
    s_rate_next_us = now + RATE_STEP_US;
    portENTER_CRITICAL(&s_mux);
    bool acq = s_st.acq_running;
    int64_t t = s_st.last_t_us;
    uint64_t p = s_st.produced;
    portEXIT_CRITICAL(&s_mux);
    if (!acq || p == 0) {
        return;
    }
    if (s_rate_n == RATE_HIST) {
        memmove(&s_rate[0], &s_rate[1], sizeof s_rate[0] * (RATE_HIST - 1));
        s_rate_n--;
    }
    s_rate[s_rate_n].t = t;
    s_rate[s_rate_n].p = p;
    s_rate_n++;
}

static void send_status(void)
{
    dec_state_t st;
    portENTER_CRITICAL(&s_mux);
    st = s_st;
    portEXIT_CRITICAL(&s_mux);
    rzl_status_hdr_t h = {
        .t_dev_us = (uint64_t)esp_timer_get_time(),
        .queue_fill = (uint8_t)(uxQueueMessagesWaiting(s_data_q) * 100u / DATA_Q_LEN),
        .sd_state = 0,   /* no SD card */
        .sd_free_mb = 0,
        .rssi_dbm = 0,   /* no Wi-Fi */
        .heap_free = (uint32_t)heap_caps_get_free_size(MALLOC_CAP_INTERNAL),
        .temp_c_x10 = 0, /* the classic ESP32 has no supported die temperature sensor */
    };
    rzl_stream_status_t s = {
        .id = STREAM_ID,
        .running = st.sending,
        .produced = st.produced,
        .device_dropped = st.device_dropped,
        .rate_mhz = rate_mhz(),
        .clipped = (uint32_t)st.clipped,
        .win_first = st.win_first,
        .win_end = st.win_end,
        .win_device = st.win_device,
        .win_link = st.win_link,
    };
    rzl_w_t w;
    rzl_payload_w(&w, s_raw, sizeof s_raw);
    rzl_enc_status(&w, &h, &s, 1);
    send_frame(RZL_STATUS, &w);
}

static void send_data(const dec_pkt_t *p)
{
    rzl_w_t w;
    rzl_payload_w(&w, s_raw, sizeof s_raw);
    rzl_enc_data(&w, STREAM_ID, N_CH, p->n, p->first, (uint64_t)p->t_us, &p->s[0][0]);
    if (!send_frame(RZL_DATA, &w)) {
        portENTER_CRITICAL(&s_mux);
        s_st.win_link += p->n; /* write error */
        portEXIT_CRITICAL(&s_mux);
    }
}

static size_t tx_backlog(void)
{
    size_t free_b = 0;
    if (uart_get_tx_buffer_free_size(LINK_UART, &free_b) != ESP_OK) {
        return LINK_TX_BUF;
    }
    return LINK_TX_BUF - free_b;
}

/* ------------------------------------------------------------------ link task: commands */
/* Ask the ADC task to stop link acquisition and wait until it has closed the open packet. */
static void stop_acquisition(bool discard)
{
    portENTER_CRITICAL(&s_mux);
    bool active = s_st.sending || s_st.acq_running || (s_req & REQ_START);
    portEXIT_CRITICAL(&s_mux);
    if (!active) {
        return;
    }
    xSemaphoreTake(s_stop_done, 0);
    portENTER_CRITICAL(&s_mux);
    s_req |= REQ_STOP | (discard ? REQ_DISCARD : 0);
    portEXIT_CRITICAL(&s_mux);
    if (xSemaphoreTake(s_stop_done, pdMS_TO_TICKS(STOP_WAIT_MS)) != pdTRUE) {
        s_stop_timeouts++;
        /* Freeze the window anyway and withdraw the request, so a later START is not cancelled by this stale STOP in
         * the same poll. The ADC task sees acq_running false at its next poll and stops by itself (link_adc_poll),
         * counting its open packet in win_link. If it took the request just now, it has already stopped. */
        portENTER_CRITICAL(&s_mux);
        s_req &= ~(REQ_STOP | REQ_DISCARD);
        if (s_st.sending) {
            s_st.win_end = s_st.produced;
            s_st.sending = false;
        }
        s_st.acq_running = false;
        portEXIT_CRITICAL(&s_mux);
    }
}

static void do_start(void)
{
    portENTER_CRITICAL(&s_mux);
    if (!s_st.sending) { /* starting a running stream is a no-op */
        /* acquisition from fully idle (adc_dec is its only consumer): indices restart at 0, window [0, 0) */
        s_st = (dec_state_t){.sending = true};
        s_req |= REQ_START;
    }
    portEXIT_CRITICAL(&s_mux);
    s_rate_n = 0;
}

static void end_session(void)
{
    stop_acquisition(true); /* implicit STOP without the drain */
    dec_pkt_t p;
    while (xQueueReceive(s_data_q, &p, 0) == pdTRUE) {
        portENTER_CRITICAL(&s_mux);
        s_st.win_link += p.n; /* send queue cleared */
        portEXIT_CRITICAL(&s_mux);
    }
    s_live = false;
}

static void start_session(int64_t now)
{
    if (!s_link_on) {
        enter_link_mode();
    }
    static const uint8_t zero = 0x00; /* separates any text from HELLO */
    uart_out(&zero, 1);
    send_hello_config();
    s_live = true;
    s_last_rx_us = now;
    s_next_status_us = now + (int64_t)s_status_ms * 1000;
}

static bool key_is(const rzl_set_t *s, const char *k)
{
    size_t n = strlen(k);
    return s->key_len == n && memcmp(s->key, k, n) == 0;
}

static void on_set(const rzl_frame_t *f)
{
    rzl_set_t s;
    if (!rzl_parse_set(f->payload, f->len, &s)) {
        send_err(f->seq, RZL_E_BAD_PAYLOAD, "bad SET payload");
        return;
    }
    if (key_is(&s, "adc.gain.0") || key_is(&s, "adc.gain.1")) {
        int ch = s.key[s.key_len - 1] - '0';
        int32_t v = s.i32;
        if (s.type != RZL_SET_I32 || v < 1 || v > 128 || (v & (v - 1)) != 0) {
            send_err(f->seq, RZL_E_BAD_VALUE, "gain must be 1, 2, 4, ... 128");
            return;
        }
        portENTER_CRITICAL(&s_mux);
        bool busy = s_st.sending || s_st.acq_running || (s_req & REQ_START);
        uint8_t old = s_gain[ch];
        uint32_t gen = s_gain_gen;
        if (!busy && old != (uint8_t)v) {
            s_gain[ch] = (uint8_t)v;
            gen = ++s_gain_gen;
        }
        portEXIT_CRITICAL(&s_mux);
        if (busy) {
            send_err(f->seq, RZL_E_BUSY, "ADC acquisition running");
            return;
        }
        /* the ADC task writes GAIN1 on its next DRDY read; wait for the ADC's acknowledgement */
        bool done = false;
        for (int i = 0; i <= GAIN_WAIT_MS && !done; i++) {
            portENTER_CRITICAL(&s_mux);
            done = (int32_t)(s_gain_applied - gen) >= 0;
            portEXIT_CRITICAL(&s_mux);
            if (!done) {
                vTaskDelay(pdMS_TO_TICKS(1));
            }
        }
        if (!done) {
            /* not confirmed (no DRDY, or no acknowledgement): go back to the old gain so the PC's CONFIG stays true;
             * the ADC task writes it again */
            portENTER_CRITICAL(&s_mux);
            s_gain[ch] = old;
            s_gain_gen++;
            portEXIT_CRITICAL(&s_mux);
            send_err(f->seq, RZL_E_BUSY, "ADC did not acknowledge the GAIN1 write");
            return;
        }
    } else if (key_is(&s, "status.period_ms")) {
        if (s.type != RZL_SET_I32 || s.i32 < 200 || s.i32 > 10000) {
            send_err(f->seq, RZL_E_BAD_VALUE, "status.period_ms must be 200 to 10000");
            return;
        }
        s_status_ms = (uint16_t)s.i32;
    } else {
        send_err(f->seq, RZL_E_UNKNOWN_KEY, "unknown key (bench firmware: adc.gain.0/1, status.period_ms)");
        return;
    }
    send_ack(f->seq);
    rzl_w_t w; /* a new CONFIG */
    uint8_t gain[N_CH];
    float scale[N_CH];
    static const uint8_t units[N_CH] = {1, 1};
    portENTER_CRITICAL(&s_mux);
    memcpy(gain, s_gain, sizeof gain);
    portEXIT_CRITICAL(&s_mux);
    for (int i = 0; i < N_CH; i++) {
        scale[i] = (float)(1.2 / (double)gain[i] / 8388608.0);
    }
    rzl_stream_cfg_t cfg = {STREAM_ID, N_CH, gain, scale, units};
    rzl_payload_w(&w, s_raw, sizeof s_raw);
    rzl_enc_config(&w, &cfg, 1, 2, s_status_ms);
    send_frame(RZL_CONFIG, &w);
}

static bool bad_mask(uint8_t m) { return m == 0 || (m & ~STREAM_MASK) != 0; }

static void on_frame(const rzl_frame_t *f, int64_t now)
{
    if (!s_live) {
        if (f->type == RZL_GET_INFO) { /* before a session every other frame is ignored */
            start_session(now);
        }
        return;
    }
    s_last_rx_us = now; /* passed COBS and CRC: counts for liveness even if answered with ERR */
    rzl_r_t r;
    rzl_r_init(&r, f->payload, f->len);
    switch (f->type) {
    case RZL_GET_INFO:
        send_hello_config(); /* inside a live session: HELLO + CONFIG again, seq reset, no 0x00 */
        break;
    case RZL_AUTH: {
        uint16_t n = rzl_get_u16(&r);
        (void)rzl_get_bytes(&r, n);
        if (r.short_) {
            send_err(f->seq, RZL_E_BAD_PAYLOAD, "payload too short");
        } /* else: accepted and ignored on this transport */
        break;
    }
    case RZL_PING: {
        uint64_t host = rzl_get_u64(&r);
        if (r.short_) {
            send_err(f->seq, RZL_E_BAD_PAYLOAD, "payload too short");
            break;
        }
        rzl_w_t w;
        rzl_payload_w(&w, s_raw, sizeof s_raw);
        rzl_enc_pong(&w, host, (uint64_t)now);
        send_frame(RZL_PONG, &w);
        break;
    }
    case RZL_START:
    case RZL_STOP: {
        uint8_t mask = rzl_get_u8(&r);
        if (r.short_) {
            send_err(f->seq, RZL_E_BAD_PAYLOAD, "payload too short");
            break;
        }
        if (bad_mask(mask)) {
            send_err(f->seq, RZL_E_BAD_VALUE, "bad stream mask (this node has adc_dec only: mask 0x02)");
            break;
        }
        if (f->type == RZL_START) {
            do_start();
            send_ack(f->seq);
            break;
        }
        /* STOP: freeze win_end, close the open packet, drain the DATA queue, final STATUS, then the ACK */
        stop_acquisition(false);
        dec_pkt_t p;
        while (xQueueReceive(s_data_q, &p, 0) == pdTRUE) {
            send_data(&p);
        }
        send_status();
        send_ack(f->seq);
        break;
    }
    case RZL_SET:
        on_set(f);
        break;
    case RZL_SD_REC: {
        uint8_t action = rzl_get_u8(&r);
        uint8_t mask = rzl_get_u8(&r);
        uint8_t n = rzl_get_u8(&r);
        (void)rzl_get_bytes(&r, n);
        if (r.short_) {
            send_err(f->seq, RZL_E_BAD_PAYLOAD, "payload too short");
        } else if (action > 1 || (action == 1 && bad_mask(mask))) {
            send_err(f->seq, RZL_E_BAD_VALUE, "bad SD_RECORD arguments");
        } else if (action == 1) {
            send_err(f->seq, RZL_E_SD, "no SD card on the bench rig");
        } else {
            send_ack(f->seq); /* stop: nothing is recording */
        }
        break;
    }
    case RZL_REBOOT:
        send_ack(f->seq);
        uart_wait_tx_done(LINK_UART, pdMS_TO_TICKS(200));
        esp_restart();
        break;
    default:
        send_err(f->seq, RZL_E_UNKNOWN_CMD, "unknown command");
        break;
    }
}

static void link_task(void *arg)
{
    (void)arg;
    static uint8_t buf[256];
    for (;;) {
        int n = uart_read_bytes(LINK_UART, buf, sizeof buf, pdMS_TO_TICKS(2));
        int64_t now = esp_timer_get_time();
        size_t pos = 0;
        while (n > 0 && pos < (size_t)n) {
            rzl_frame_t f;
            bool got = false;
            pos += rzl_rx_feed(&s_rx, buf + pos, (size_t)n - pos, &f, &got);
            if (got) {
                on_frame(&f, now);
                now = esp_timer_get_time();
            }
        }
        if (!s_live) {
            continue;
        }
        if (now - s_last_rx_us > LIVENESS_US) {
            end_session(); /* no valid PC frame for 5 s */
            continue;
        }
        rate_sample(now);
        if (now >= s_next_status_us) {
            send_status();
            s_next_status_us = now + (int64_t)s_status_ms * 1000;
        }
        dec_pkt_t p;
        while (tx_backlog() < LINK_TX_HIGH && xQueueReceive(s_data_q, &p, 0) == pdTRUE) {
            send_data(&p);
        }
    }
}

void link_init(void)
{
    s_txt_lock = xSemaphoreCreateMutex();
    s_stop_done = xSemaphoreCreateBinary();
    s_data_q = xQueueCreate(DATA_Q_LEN, sizeof(dec_pkt_t));
    rzl_rx_init(&s_rx);
    uint8_t mac[6] = {0};
    esp_read_mac(mac, ESP_MAC_WIFI_STA);
    snprintf(s_node_id, sizeof s_node_id, "rzn-%02x%02x%02x", mac[3], mac[4], mac[5]);
    /* UART0 keeps its console configuration (115200 8N1); the driver adds the RX and TX rings. In text mode stdout
     * still writes the FIFO directly (VFS, no driver), so text and frames never mix: text stops before the first
     * frame. */
    ESP_ERROR_CHECK(uart_driver_install(LINK_UART, LINK_RX_BUF, LINK_TX_BUF, 0, NULL, 0));
    xTaskCreatePinnedToCore(link_task, "link", 4096, NULL, 6, NULL, 0);
}
