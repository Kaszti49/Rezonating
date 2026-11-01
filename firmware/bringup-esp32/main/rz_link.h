/*
 * Link protocol v0 codec (tools/lab/PROTOCOL.md, D-018): CRC-16/CCITT-FALSE, COBS as pinned in section 2,
 * little-endian payload writers and readers, the node -> PC messages this bench firmware sends, and a byte-stream
 * receiver for PC -> node frames.
 *
 * Portable C99: no ESP-IDF headers, so test_host/ compiles it on the PC against tools/lab/tests/vectors/link-v0.json.
 */
#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define RZL_VER           0
#define RZL_HEADER_LEN    4
#define RZL_CRC_LEN       2
#define RZL_MIN_RAW       (RZL_HEADER_LEN + RZL_CRC_LEN)        /* 6 */
#define RZL_MAX_PAYLOAD   4096
#define RZL_MAX_RAW       (RZL_HEADER_LEN + RZL_MAX_PAYLOAD + RZL_CRC_LEN) /* 4102 */
#define RZL_MAX_ENCODED   (RZL_MAX_RAW + (RZL_MAX_RAW + 253) / 254)   /* 4119, without the delimiter */
#define RZL_WIRE_LEN(raw) ((raw) + ((raw) + 253) / 254 + 1)         /* worst case incl. the 0x00 */

/* Frame types (section 3) */
#define RZL_HELLO    0x01
#define RZL_DATA     0x02
#define RZL_STATUS   0x03
#define RZL_EVENT    0x04
#define RZL_LOG      0x05
#define RZL_ACK      0x06
#define RZL_ERR      0x07
#define RZL_PONG     0x08
#define RZL_CONFIG   0x09
#define RZL_GET_INFO 0x81
#define RZL_START    0x82
#define RZL_STOP     0x83
#define RZL_SET      0x84
#define RZL_SD_REC   0x85
#define RZL_PING     0x86
#define RZL_REBOOT   0x87
#define RZL_AUTH     0x88

/* ERR codes (section 4.7) */
#define RZL_E_UNKNOWN_CMD 1
#define RZL_E_BAD_PAYLOAD 2
#define RZL_E_UNKNOWN_KEY 3
#define RZL_E_BAD_VALUE   4
#define RZL_E_BUSY        5
#define RZL_E_NOT_AUTH    6
#define RZL_E_SD          7

/* SET value types (section 5) */
#define RZL_SET_I32    0
#define RZL_SET_F32    1
#define RZL_SET_STR8   2
#define RZL_SET_BLOB16 3

uint16_t rzl_crc16(const uint8_t *data, size_t len);

/* COBS-encode n >= 1 bytes into out (room for n + ceil(n / 254)); returns the encoded length (no delimiter). */
size_t rzl_cobs_encode(const uint8_t *raw, size_t n, uint8_t *out);
/* Inverse; returns the decoded length, or -1 on malformed input or when it would exceed out_cap. */
int rzl_cobs_decode(const uint8_t *enc, size_t n, uint8_t *out, size_t out_cap);

/* ------------------------------------------------------------------ payload writer */
typedef struct {
    uint8_t *p;
    size_t n;
    size_t cap;
    bool overflow; /* a put did not fit: the payload is invalid */
} rzl_w_t;

void rzl_w_init(rzl_w_t *w, uint8_t *buf, size_t cap);
void rzl_put_u8(rzl_w_t *w, uint8_t v);
void rzl_put_u16(rzl_w_t *w, uint16_t v);
void rzl_put_u32(rzl_w_t *w, uint32_t v);
void rzl_put_u64(rzl_w_t *w, uint64_t v);
void rzl_put_i32(rzl_w_t *w, int32_t v);
void rzl_put_f32(rzl_w_t *w, float v);
void rzl_put_bytes(rzl_w_t *w, const void *b, size_t len);
void rzl_put_str8(rzl_w_t *w, const char *s);  /* truncated to 255 B on a UTF-8 code point boundary */
void rzl_put_blob16(rzl_w_t *w, const uint8_t *b, uint16_t len);

/* Frame assembly. buf holds the raw frame: the payload is written at buf + RZL_HEADER_LEN (use rzl_payload_w), then
 * rzl_finish writes the header and CRC around it and COBS-encodes the whole into wire (room for
 * RZL_WIRE_LEN(RZL_HEADER_LEN + payload_len + RZL_CRC_LEN)). Returns the wire length including the 0x00. */
void rzl_payload_w(rzl_w_t *w, uint8_t *buf, size_t buf_cap);
size_t rzl_finish(uint8_t *buf, size_t payload_len, uint8_t type, uint16_t seq, uint8_t *wire);

/* ------------------------------------------------------------------ node -> PC messages */
typedef struct {
    uint8_t id, n_ch;
    uint32_t nominal_hz;
    uint8_t bits, clock;
    uint16_t fir_taps, fir_delay;
} rzl_stream_info_t;

typedef struct {
    uint8_t port;
    const uint8_t *descriptor;
    uint16_t len;
} rzl_head_info_t;

typedef struct {
    uint8_t id, n_ch;
    const uint8_t *gain; /* n_ch each */
    const float *scale;
    const uint8_t *units;
} rzl_stream_cfg_t;

typedef struct {
    uint8_t id, running;
    uint64_t produced, device_dropped;
    uint32_t rate_mhz, clipped;
    uint64_t win_first, win_end, win_device, win_link;
} rzl_stream_status_t;

typedef struct {
    uint64_t t_dev_us;
    uint8_t queue_fill, sd_state;
    uint32_t sd_free_mb;
    int8_t rssi_dbm;
    uint32_t heap_free;
    int16_t temp_c_x10;
} rzl_status_hdr_t;

void rzl_enc_hello(rzl_w_t *w, uint8_t proto, const char *fw, const char *node_id, uint64_t t_dev_us,
                   const rzl_stream_info_t *s, uint8_t n_s, const rzl_head_info_t *h, uint8_t n_h);
void rzl_enc_config(rzl_w_t *w, const rzl_stream_cfg_t *s, uint8_t n_s, uint8_t accel_range_g,
                    uint16_t status_period_ms);
/* samples: n * n_ch int32, frame-major */
void rzl_enc_data(rzl_w_t *w, uint8_t stream, uint8_t n_ch, uint16_t n, uint64_t first_sample, uint64_t t_dev_us,
                  const int32_t *samples);
void rzl_enc_status(rzl_w_t *w, const rzl_status_hdr_t *hdr, const rzl_stream_status_t *s, uint8_t n_s);
void rzl_enc_ack(rzl_w_t *w, uint16_t cmd_seq);
void rzl_enc_err(rzl_w_t *w, uint16_t cmd_seq, uint16_t code, const char *msg);
void rzl_enc_pong(rzl_w_t *w, uint64_t host_t_us, uint64_t t_dev_us);

/* ------------------------------------------------------------------ payload reader */
typedef struct {
    const uint8_t *p;
    size_t n;
    size_t pos;
    bool short_; /* a get ran past the end: the payload is too short (ERR 2) */
} rzl_r_t;

void rzl_r_init(rzl_r_t *r, const uint8_t *p, size_t n);
uint8_t rzl_get_u8(rzl_r_t *r);
uint16_t rzl_get_u16(rzl_r_t *r);
uint32_t rzl_get_u32(rzl_r_t *r);
uint64_t rzl_get_u64(rzl_r_t *r);
/* Returns a pointer into the payload and its length (not NUL-terminated); NULL when short. */
const uint8_t *rzl_get_bytes(rzl_r_t *r, size_t len);

/* ------------------------------------------------------------------ receiver (section 2, receiver rules) */
typedef struct {
    uint8_t chunk[RZL_MAX_ENCODED];
    size_t len;
    bool discarding;     /* more than RZL_MAX_ENCODED bytes without a 0x00: swallow up to the next 0x00 */
    uint32_t bad_frames; /* chunks dropped: oversize, COBS, length, CRC, ver */
    uint32_t frames_ok;
    uint8_t raw[RZL_MAX_RAW];
} rzl_rx_t;

typedef struct {
    uint8_t type;
    uint16_t seq;
    const uint8_t *payload; /* points into the receiver; valid until the next rzl_rx_feed call */
    size_t len;
} rzl_frame_t;

void rzl_rx_init(rzl_rx_t *rx);
/* Feed bytes; returns how many were consumed. Stops right after a complete valid frame (*got = true, *f filled) so
 * the caller handles frames one at a time; call again with the rest. */
size_t rzl_rx_feed(rzl_rx_t *rx, const uint8_t *data, size_t n, rzl_frame_t *f, bool *got);

/* ------------------------------------------------------------------ PC -> node payloads */
typedef struct {
    const uint8_t *key; /* not NUL-terminated */
    uint8_t key_len;
    uint8_t type; /* RZL_SET_* */
    int32_t i32;
    float f32;
    const uint8_t *bytes; /* str8 / blob16 value */
    uint16_t bytes_len;
} rzl_set_t;

/* SET payload: str8 key, u8 type, value (codec.Set.from_payload). Returns false when the payload is too short or the
 * value type is unknown: both are ERR 2 (bad payload), checked before the key. */
bool rzl_parse_set(const uint8_t *p, size_t n, rzl_set_t *s);
