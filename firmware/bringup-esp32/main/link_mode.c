/*
 * Bench link mode (see link_mode.h, README.md "Link mode"). Link streams: adc_dec (id 1, 2 channels, 1000 Hz nominal,
 * D-016 63-tap FIR / 2, fir_delay 31) and, on the ESP32-S3 rig, adc_raw (id 0, 2 channels, 2000 Hz nominal, the ADC
 * codes as read). Session rules: PROTOCOL.md section 1, USB row: over UART0 on the classic ESP32 (the text report
 * shares the port and stops for good when the link starts), over the native USB-Serial/JTAG port on the ESP32-S3 (the
 * text report keeps running on UART0).
 *
 * Data path: the ADC task (core 1, priority 10) runs the FIR and fills packets (adc_raw 80 frames, adc_dec 40 frames:
 * about 25 DATA frames per second per stream, PROTOCOL.md 4.3); a full packet goes into one FreeRTOS queue with a
 * zero timeout, so the ADC task never waits for the link. A packet that does not fit is counted in its stream's
 * win_link. The link task (core 0) is the only writer of the link transport: it answers commands (control frames go
 * out first), sends STATUS every status.period_ms and writes queued DATA while the transport takes it.
 */
#include "link_mode.h"

#include <inttypes.h>
#include <stdarg.h>
#include <stdio.h>
#include <string.h>

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
#include "rig.h"
#include "rz_decim.h"
#include "rz_link.h"
#if RIG_LINK_USJ
#include "driver/usb_serial_jtag.h"
#else
#include "driver/uart.h"
#endif

#define LINK_RX_BUF 1024 /* driver RX ring: > SOC_UART_FIFO_LEN (128) and > 64 (USB-Serial/JTAG minimum) */
#if RIG_LINK_USJ
#define LINK_TX_BUF 8192 /* USB-Serial/JTAG TX ring: about 0.3 s of both streams if the PC stops reading */
#else
#define LINK_UART   UART_NUM_0
#define LINK_TX_BUF 2048 /* UART driver TX ring */
#define LINK_TX_HIGH 512 /* queue DATA only while fewer bytes wait in the TX ring: control frames wait <= ~75 ms */
#endif
#define CTRL_WAIT_MS 50 /* a control frame waits this long for room in the TX ring (USB-Serial/JTAG) */
#define S_RAW        0  /* stream ids (PROTOCOL.md 4.1) = index into s_st and s_pkt */
#define S_DEC        1
#define N_STREAMS    2
#define PKT_DEC      40 /* 1000 Hz / 40 = 25 DATA frames per second */
#define PKT_RAW      80 /* 2000 Hz / 80 = 25 per second, 640 B of samples */
#if RIG_HAS_RAW
#define LINK_MASK  0x03u /* adc_raw and adc_dec */
#define PKT_MAX    PKT_RAW
#define DATA_Q_LEN 128 /* packets: 2.56 s at 50 per second, about 85 kB internal RAM */
#else
#define LINK_MASK  0x02u /* adc_dec only */
#define PKT_MAX    PKT_DEC
#define DATA_Q_LEN 64 /* packets: 2.56 s at 25 per second (no PSRAM on the classic board) */
#endif
#define N_CH         2
#define LIVENESS_US  5000000
#define STOP_WAIT_MS 500 /* the ADC task polls requests at least every 100 ms (its DRDY timeout) */
#define GAIN_WAIT_MS 100
#define RATE_HIST    21 /* one point per 500 ms: 10 s */
#define RATE_STEP_US 500000
#define FW_VERSION   "bringup-0.3.0"
#define CODE_MAX     8388607
#define CODE_MIN     (-8388608)

#define REQ_START   1u
#define REQ_STOP    2u
#define REQ_DISCARD 4u /* with REQ_STOP: session end, the open packets are not sent (counted in win_link) */

typedef struct {
    uint64_t first;
    int64_t t_us;
    uint16_t n;
    uint8_t stream;
    int32_t s[PKT_MAX][N_CH];
} pkt_t;

/* Per link stream (PROTOCOL.md 4.4), guarded by s_mux. */
typedef struct {
    bool sending;
    uint64_t produced;
    uint64_t device_dropped;
    uint64_t clipped;
    uint64_t win_first, win_end, win_device, win_link;
} stream_state_t;

static portMUX_TYPE s_mux = portMUX_INITIALIZER_UNLOCKED;
static stream_state_t s_st[N_STREAMS];
static bool s_acq_running;      /* ADC acquisition for the link: from a START out of idle until no stream sends */
static int64_t s_last_t_us;     /* DRDY time of the newest raw sample (index s_st[S_RAW].produced - 1) */
static uint32_t s_req;          /* REQ_*, guarded by s_mux */
static uint8_t s_req_stop_mask; /* streams the pending REQ_STOP stops */
static uint8_t s_gain[N_CH] = {RIG_ADC_GAIN, RIG_ADC_GAIN};
static uint32_t s_gain_gen;     /* bumped by SET adc.gain.*, guarded by s_mux */
static uint32_t s_gain_applied; /* last generation the ADC acknowledged */
static uint32_t s_gain_fail;    /* GAIN1 writes the ADC did not acknowledge (retried) */
static SemaphoreHandle_t s_stop_done;
static QueueHandle_t s_data_q;

/* ADC task private */
static bool s_acq;
static rz_decim_t s_dec;
static pkt_t s_pkt[N_STREAMS];

/* text gate */
static SemaphoreHandle_t s_txt_lock;
static volatile bool s_link_on;
#define TEXT_SHARES_LINK (!RIG_LINK_USJ) /* text and frames on the same port: text stops when the link starts */

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
static pkt_t s_tx_pkt;
static struct {
    int64_t t;
    uint64_t p; /* raw samples produced */
} s_rate[RATE_HIST];
static int s_rate_n;
static int64_t s_rate_next_us;
static uint32_t s_stop_timeouts; /* STOP whose drain the ADC task did not confirm in time */

/* ------------------------------------------------------------------ text gate */
void link_txt(const char *fmt, ...)
{
    if (link_text_off()) {
        return;
    }
    if (s_txt_lock != NULL) {
        xSemaphoreTake(s_txt_lock, portMAX_DELAY);
    }
    if (!link_text_off()) {
        va_list ap;
        va_start(ap, fmt);
        vprintf(fmt, ap);
        va_end(ap);
    }
    if (s_txt_lock != NULL) {
        xSemaphoreGive(s_txt_lock);
    }
}

bool link_text_off(void) { return TEXT_SHARES_LINK && s_link_on; }

#if TEXT_SHARES_LINK
static int null_vprintf(const char *fmt, va_list ap)
{
    (void)fmt;
    (void)ap;
    return 0;
}
#endif

/* Classic ESP32: text off for good: no line can start after this, the partial line in stdout goes out before the
 * session's 0x00, ESP_LOG is silenced and the ROM printf channels (esp_rom_printf, early and DRAM logs) are
 * disconnected. ESP32-S3: the console stays on UART0; only the ROM's USB-Serial/JTAG print channel (2) is
 * disconnected, so no ROM text lands between frames (PROTOCOL.md 1, "Console"). */
static void enter_link_mode(void)
{
    xSemaphoreTake(s_txt_lock, portMAX_DELAY);
    s_link_on = true;
    fflush(stdout);
    xSemaphoreGive(s_txt_lock);
#if TEXT_SHARES_LINK
    esp_log_level_set("*", ESP_LOG_NONE);
    esp_log_set_vprintf(null_vprintf);
    esp_rom_install_channel_putc(1, NULL);
#endif
    esp_rom_install_channel_putc(2, NULL);
}

/* ------------------------------------------------------------------ ADC task side */
static void pkt_flush(int id, bool discard)
{
    pkt_t *p = &s_pkt[id];
    if (p->n == 0) {
        return;
    }
    if (discard || xQueueSend(s_data_q, p, 0) != pdTRUE) {
        portENTER_CRITICAL(&s_mux);
        s_st[id].win_link += p->n; /* never handed to the transport */
        portEXIT_CRITICAL(&s_mux);
    }
    p->n = 0;
}

static void pkt_add(int id, uint64_t idx, int64_t t_us, const int32_t *v)
{
    pkt_t *p = &s_pkt[id];
    if (p->n == 0) {
        p->first = idx;
        p->t_us = t_us;
        p->stream = (uint8_t)id;
    }
    p->s[p->n][0] = v[0];
    p->s[p->n][1] = v[1];
    if (++p->n == (id == S_RAW ? PKT_RAW : PKT_DEC)) {
        pkt_flush(id, false);
    }
}

void link_adc_poll(void)
{
    portENTER_CRITICAL(&s_mux);
    uint32_t req = s_req;
    uint8_t stop_mask = s_req_stop_mask;
    s_req = 0;
    s_req_stop_mask = 0;
    if (req & REQ_START) {
        s_acq_running = true;
    }
    if (req & REQ_STOP) {
        for (int id = 0; id < N_STREAMS; id++) {
            if ((stop_mask & (1u << id)) && s_st[id].sending) {
                s_st[id].win_end = s_st[id].produced; /* every index below it is computed: only the open packet is left */
                s_st[id].sending = false;
            }
        }
        if (!s_st[S_RAW].sending && !s_st[S_DEC].sending) {
            s_acq_running = false;
        }
    }
    bool sending[N_STREAMS] = {s_st[S_RAW].sending, s_st[S_DEC].sending};
    bool acq_running = s_acq_running;
    portEXIT_CRITICAL(&s_mux);
    if (req & REQ_STOP) {
        for (int id = 0; id < N_STREAMS; id++) {
            if (stop_mask & (1u << id)) {
                pkt_flush(id, (req & REQ_DISCARD) != 0);
            }
        }
    }
    /* open packets of streams no longer sending (a STOP the link task gave up waiting for): not sent */
    for (int id = 0; id < N_STREAMS; id++) {
        if (!sending[id]) {
            pkt_flush(id, true);
        }
    }
    if (!acq_running) {
        s_acq = false;
    } else if (req & REQ_START) {
        rz_decim_init(&s_dec, N_CH); /* acquisition from idle: index 0 is the next DRDY, FIR history zeros */
        s_pkt[S_RAW].n = 0;
        s_pkt[S_DEC].n = 0;
        s_acq = true;
    }
    if (req & REQ_STOP) {
        xSemaphoreGive(s_stop_done);
    }
}

void link_adc_sample(int64_t t_us, bool ok, const int32_t *ch)
{
    if (!s_acq) {
        return;
    }
    uint64_t r = s_dec.n_in; /* raw index of this sample interval */
    float y[N_CH];
    bool valid = false;
    bool out = rz_decim_push(&s_dec, ch, ok, y, &valid);
    bool rclip = false;
    if (ok) {
        for (int i = 0; i < N_CH; i++) {
            rclip |= ch[i] >= CODE_MAX || ch[i] <= CODE_MIN;
        }
    }
    uint64_t k = 0;
    int32_t c[N_CH] = {0};
    bool dclip = false;
    if (out) {
        k = (r - 1) / 2; /* output after raw sample 2k + 1 */
        for (int i = 0; i < N_CH; i++) {
            c[i] = rz_decim_code(y[i]);
            dclip |= c[i] >= CODE_MAX || c[i] <= CODE_MIN;
        }
    }

    portENTER_CRITICAL(&s_mux);
    if (s_req & REQ_START) {
        /* a restart from idle is waiting for the next poll (possible only after a STOP that timed out, while this task
         * still ran the old acquisition): the indices restart there, so this old sample belongs to no window */
        portEXIT_CRITICAL(&s_mux);
        return;
    }
    s_last_t_us = t_us;
    stream_state_t *R = &s_st[S_RAW];
    R->produced = r + 1;
    bool rsend = R->sending;
    if (!ok) {
        R->device_dropped++; /* missed DRDY or failed read */
        if (rsend) {
            R->win_device++;
        }
    } else if (rclip) {
        R->clipped++;
    }
    if (rsend) {
        R->win_end = R->produced;
    }
    bool dsend = false;
    if (out) {
        stream_state_t *D = &s_st[S_DEC];
        D->produced = k + 1;
        dsend = D->sending;
        if (!valid) {
            D->device_dropped++; /* a lost raw sample inside the FIR window: not sent */
            if (dsend) {
                D->win_device++;
            }
        } else if (dclip) {
            D->clipped++;
        }
        if (dsend) {
            D->win_end = D->produced;
        }
    }
    portEXIT_CRITICAL(&s_mux);

    if (rsend) {
        if (ok) {
            pkt_add(S_RAW, r, t_us, ch);
        } else {
            pkt_flush(S_RAW, false); /* a drop ends the packet; the next one starts after the gap */
        }
    }
    if (dsend) {
        if (valid) {
            pkt_add(S_DEC, k, t_us, c);
        } else {
            pkt_flush(S_DEC, false);
        }
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

/* ------------------------------------------------------------------ link task: transport */
/* All or nothing: true when all n bytes went into the transport's TX ring. */
static bool tx_write(const uint8_t *b, size_t n, uint32_t wait_ms)
{
#if RIG_LINK_USJ
    return usb_serial_jtag_write_bytes(b, n, pdMS_TO_TICKS(wait_ms)) == (int)n; /* the ring takes all or nothing */
#else
    (void)wait_ms; /* uart_write_bytes blocks until everything is in the ring */
    return uart_write_bytes(LINK_UART, b, n) == (int)n;
#endif
}

static int rx_read(uint8_t *b, size_t n, uint32_t wait_ms)
{
#if RIG_LINK_USJ
    return usb_serial_jtag_read_bytes(b, (uint32_t)n, pdMS_TO_TICKS(wait_ms));
#else
    return uart_read_bytes(LINK_UART, b, (uint32_t)n, pdMS_TO_TICKS(wait_ms));
#endif
}

static void tx_wait_done(uint32_t wait_ms)
{
#if RIG_LINK_USJ
    (void)usb_serial_jtag_wait_tx_done(pdMS_TO_TICKS(wait_ms));
#else
    (void)uart_wait_tx_done(LINK_UART, pdMS_TO_TICKS(wait_ms));
#endif
}

/* Room for DATA without delaying control frames. USB-Serial/JTAG has no fill level: DATA is written with no wait and
 * stays queued when the ring is full. */
static bool data_room(void)
{
#if RIG_LINK_USJ
    return true;
#else
    size_t free_b = 0;
    if (uart_get_tx_buffer_free_size(LINK_UART, &free_b) != ESP_OK) {
        return false;
    }
    return LINK_TX_BUF - free_b < LINK_TX_HIGH;
#endif
}

/* ------------------------------------------------------------------ link task: output */
#define TX_OK   1
#define TX_FULL 0  /* the transport did not take it: nothing written, seq not spent */
#define TX_BAD  -1 /* the payload did not fit the frame buffer */

/* Header, CRC, COBS; the seq is spent only when the frame is written (PROTOCOL.md 2). */
static int send_frame_wait(uint8_t type, const rzl_w_t *w, uint32_t wait_ms)
{
    if (w->overflow) {
        return TX_BAD;
    }
    size_t n = rzl_finish(s_raw, w->n, type, s_tx_seq, s_wire);
    if (!tx_write(s_wire, n, wait_ms)) {
        return TX_FULL;
    }
    s_tx_seq++;
    return TX_OK;
}

static bool send_frame(uint8_t type, const rzl_w_t *w) { return send_frame_wait(type, w, CTRL_WAIT_MS) == TX_OK; }

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

static void send_config(void)
{
    uint8_t gain[N_CH];
    float scale[N_CH];
    static const uint8_t units[N_CH] = {1, 1}; /* V at the ADC input */
    portENTER_CRITICAL(&s_mux);
    memcpy(gain, s_gain, sizeof gain);
    portEXIT_CRITICAL(&s_mux);
    for (int i = 0; i < N_CH; i++) {
        scale[i] = (float)(1.2 / (double)gain[i] / 8388608.0); /* 1.2 V / gain / 2^23 */
    }
    /* both ADC streams carry the same codes: same gain and scale */
    const rzl_stream_cfg_t cfg[] = {
#if RIG_HAS_RAW
        {S_RAW, N_CH, gain, scale, units},
#endif
        {S_DEC, N_CH, gain, scale, units},
    };
    rzl_w_t w;
    rzl_payload_w(&w, s_raw, sizeof s_raw);
    rzl_enc_config(&w, cfg, (uint8_t)(sizeof cfg / sizeof cfg[0]), 2 /* accel_range_g: no accel on this rig */,
                   s_status_ms);
    send_frame(RZL_CONFIG, &w);
}

static void send_hello_config(void)
{
    static const rzl_stream_info_t streams[] = {
#if RIG_HAS_RAW
        {S_RAW, N_CH, 2000, 24, 0 /* ltc6903 */, 0, 0},
#endif
        {S_DEC, N_CH, 1000, 24, 0 /* ltc6903 */, RZ_DECIM_TAPS, RZ_DECIM_DELAY},
    };
    s_tx_seq = 0; /* the node resets its seq at every HELLO */
    rzl_w_t w;
    rzl_payload_w(&w, s_raw, sizeof s_raw);
    rzl_enc_hello(&w, 0, FW_VERSION, s_node_id, (uint64_t)esp_timer_get_time(), streams,
                  (uint8_t)(sizeof streams / sizeof streams[0]), NULL, 0);
    send_frame(RZL_HELLO, &w);
    send_config();
}

/* Raw samples per second over the last 10 s, in mHz (indices assigned against the ESP32 us clock). */
static uint32_t rate_raw_mhz(void)
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
    bool acq = s_acq_running;
    int64_t t = s_last_t_us;
    uint64_t p = s_st[S_RAW].produced;
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

static void fill_status(rzl_stream_status_t *s, const stream_state_t *st, uint8_t id, uint32_t rate_mhz)
{
    *s = (rzl_stream_status_t){
        .id = id,
        .running = st->sending,
        .produced = st->produced,
        .device_dropped = st->device_dropped,
        .rate_mhz = rate_mhz,
        .clipped = (uint32_t)st->clipped,
        .win_first = st->win_first,
        .win_end = st->win_end,
        .win_device = st->win_device,
        .win_link = st->win_link,
    };
}

static void send_status(void)
{
    stream_state_t st[N_STREAMS];
    portENTER_CRITICAL(&s_mux);
    memcpy(st, s_st, sizeof st);
    portEXIT_CRITICAL(&s_mux);
    rzl_status_hdr_t h = {
        .t_dev_us = (uint64_t)esp_timer_get_time(),
        .queue_fill = (uint8_t)(uxQueueMessagesWaiting(s_data_q) * 100u / DATA_Q_LEN),
        .sd_state = 0, /* no SD card */
        .sd_free_mb = 0,
        .rssi_dbm = 0, /* no Wi-Fi */
        .heap_free = (uint32_t)heap_caps_get_free_size(MALLOC_CAP_INTERNAL),
        .temp_c_x10 = 0, /* die temperature not read on the bench rigs */
    };
    uint32_t raw_mhz = rate_raw_mhz();
    rzl_stream_status_t s[N_STREAMS];
    int n = 0;
#if RIG_HAS_RAW
    fill_status(&s[n++], &st[S_RAW], S_RAW, raw_mhz);
#endif
    fill_status(&s[n++], &st[S_DEC], S_DEC, raw_mhz / 2); /* adc_dec reports the raw rate / 2 (PROTOCOL.md 4.4) */
    rzl_w_t w;
    rzl_payload_w(&w, s_raw, sizeof s_raw);
    rzl_enc_status(&w, &h, s, (uint8_t)n);
    send_frame(RZL_STATUS, &w);
}

static void count_link_loss(const pkt_t *p)
{
    portENTER_CRITICAL(&s_mux);
    s_st[p->stream].win_link += p->n;
    portEXIT_CRITICAL(&s_mux);
}

static int send_data(const pkt_t *p, uint32_t wait_ms)
{
    rzl_w_t w;
    rzl_payload_w(&w, s_raw, sizeof s_raw);
    rzl_enc_data(&w, p->stream, N_CH, p->n, p->first, (uint64_t)p->t_us, &p->s[0][0]);
    return send_frame_wait(RZL_DATA, &w, wait_ms);
}

/* Queued DATA, oldest first, while the transport takes it; a packet the transport has no room for stays queued. */
static void send_queued_data(void)
{
    while (data_room() && xQueuePeek(s_data_q, &s_tx_pkt, 0) == pdTRUE) {
        int r = send_data(&s_tx_pkt, 0);
        if (r == TX_FULL) {
            return;
        }
        (void)xQueueReceive(s_data_q, &s_tx_pkt, 0);
        if (r == TX_BAD) {
            count_link_loss(&s_tx_pkt);
        }
    }
}

/* Everything still queued, waiting for room (STOP's drain); what the transport does not take counts in win_link. */
static void drain_queued_data(void)
{
    while (xQueueReceive(s_data_q, &s_tx_pkt, 0) == pdTRUE) {
        if (send_data(&s_tx_pkt, CTRL_WAIT_MS) != TX_OK) {
            count_link_loss(&s_tx_pkt);
        }
    }
}

/* ------------------------------------------------------------------ link task: commands */
static bool any_sending(void) { return s_st[S_RAW].sending || s_st[S_DEC].sending; }

/* Ask the ADC task to stop the streams in mask and wait until it has closed their open packets. */
static void stop_streams(uint8_t mask, bool discard)
{
    portENTER_CRITICAL(&s_mux);
    bool active = (s_req & REQ_START) != 0;
    for (int id = 0; id < N_STREAMS; id++) {
        active |= (mask & (1u << id)) && s_st[id].sending;
    }
    portEXIT_CRITICAL(&s_mux);
    if (!active) {
        return;
    }
    xSemaphoreTake(s_stop_done, 0);
    portENTER_CRITICAL(&s_mux);
    s_req |= REQ_STOP | (discard ? REQ_DISCARD : 0);
    s_req_stop_mask |= mask;
    portEXIT_CRITICAL(&s_mux);
    if (xSemaphoreTake(s_stop_done, pdMS_TO_TICKS(STOP_WAIT_MS)) != pdTRUE) {
        s_stop_timeouts++;
        /* Freeze the windows anyway and withdraw the request, so a later START is not cancelled by this stale STOP in
         * the same poll. The ADC task sees the streams not sending at its next poll and drops their open packets by
         * itself (link_adc_poll), counting them in win_link. If it took the request just now, it has already stopped. */
        portENTER_CRITICAL(&s_mux);
        s_req &= ~(REQ_STOP | REQ_DISCARD);
        s_req_stop_mask = 0;
        for (int id = 0; id < N_STREAMS; id++) {
            if ((mask & (1u << id)) && s_st[id].sending) {
                s_st[id].win_end = s_st[id].produced;
                s_st[id].sending = false;
            }
        }
        if (!any_sending()) {
            s_acq_running = false;
        }
        portEXIT_CRITICAL(&s_mux);
    }
}

static void do_start(uint8_t mask)
{
    portENTER_CRITICAL(&s_mux);
    /* acquisition from fully idle: indices restart at 0 for both streams (PROTOCOL.md 4.3, acquisition lifecycle) */
    bool idle = !any_sending() && !s_acq_running && !(s_req & REQ_START);
    if (idle) {
        memset(s_st, 0, sizeof s_st);
        s_req |= REQ_START;
    }
    for (int id = 0; id < N_STREAMS; id++) {
        stream_state_t *st = &s_st[id];
        if ((mask & (1u << id)) && !st->sending) { /* starting a running stream is a no-op */
            st->sending = true;
            st->win_first = st->produced;
            st->win_end = st->produced;
            st->win_device = 0;
            st->win_link = 0;
        }
    }
    portEXIT_CRITICAL(&s_mux);
    if (idle) {
        s_rate_n = 0;
    }
}

static void end_session(void)
{
    stop_streams(LINK_MASK, true); /* implicit STOP without the drain */
    while (xQueueReceive(s_data_q, &s_tx_pkt, 0) == pdTRUE) {
        count_link_loss(&s_tx_pkt); /* send queue cleared */
    }
    s_live = false;
}

static void start_session(int64_t now)
{
    if (!s_link_on) {
        enter_link_mode();
    }
    static const uint8_t zero = 0x00; /* separates any text from HELLO */
    (void)tx_write(&zero, 1, CTRL_WAIT_MS);
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
        bool busy = any_sending() || s_acq_running || (s_req & REQ_START);
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
    send_config(); /* a new CONFIG */
}

static bool bad_mask(uint8_t m) { return m == 0 || (m & ~LINK_MASK) != 0; }

#if RIG_HAS_RAW
#define BAD_MASK_MSG "bad stream mask (this node has adc_raw and adc_dec: mask 0x01 to 0x03)"
#else
#define BAD_MASK_MSG "bad stream mask (this node has adc_dec only: mask 0x02)"
#endif

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
            send_err(f->seq, RZL_E_BAD_VALUE, BAD_MASK_MSG);
            break;
        }
        if (f->type == RZL_START) {
            do_start(mask);
            send_ack(f->seq);
            break;
        }
        /* STOP: freeze win_end, close the open packets, drain the DATA queue, final STATUS, then the ACK */
        stop_streams(mask, false);
        drain_queued_data();
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
        tx_wait_done(200);
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
        int n = rx_read(buf, sizeof buf, 2);
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
        send_queued_data();
    }
}

void link_init(void)
{
    s_txt_lock = xSemaphoreCreateMutex();
    s_stop_done = xSemaphoreCreateBinary();
    s_data_q = xQueueCreate(DATA_Q_LEN, sizeof(pkt_t));
    configASSERT(s_data_q != NULL);
    rzl_rx_init(&s_rx);
    uint8_t mac[6] = {0};
    esp_read_mac(mac, ESP_MAC_WIFI_STA);
    snprintf(s_node_id, sizeof s_node_id, "rzn-%02x%02x%02x", mac[3], mac[4], mac[5]);
#if RIG_LINK_USJ
    /* The console is on UART0 (sdkconfig.defaults: CONFIG_ESP_CONSOLE_UART_DEFAULT, no secondary console), so this
     * driver is the only user of the USB-Serial/JTAG port. */
    usb_serial_jtag_driver_config_t cfg = {.tx_buffer_size = LINK_TX_BUF, .rx_buffer_size = LINK_RX_BUF};
    ESP_ERROR_CHECK(usb_serial_jtag_driver_install(&cfg));
#else
    /* UART0 keeps its console configuration (115200 8N1); the driver adds the RX and TX rings. In text mode stdout
     * still writes the FIFO directly (VFS, no driver), so text and frames never mix: text stops before the first
     * frame. */
    ESP_ERROR_CHECK(uart_driver_install(LINK_UART, LINK_RX_BUF, LINK_TX_BUF, 0, NULL, 0));
#endif
    xTaskCreatePinnedToCore(link_task, "link", 4096, NULL, 6, NULL, 0);
}
