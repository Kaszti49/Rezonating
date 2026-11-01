/*
 * Link protocol v0 codec. See rz_link.h. Every rule here follows tools/lab/PROTOCOL.md sections 2 to 5 and the Python
 * reference tools/lab/src/rezonating_lab/link/{crc,cobs,codec,receiver}.py.
 */
#include "rz_link.h"

#include <string.h>

/* CRC-16/CCITT-FALSE: poly 0x1021, init 0xFFFF, not reflected, xorout 0 (section 2). Check value "123456789" 0x29B1. */
uint16_t rzl_crc16(const uint8_t *data, size_t len)
{
    uint16_t crc = 0xFFFF;
    for (size_t i = 0; i < len; i++) {
        crc ^= (uint16_t)((uint16_t)data[i] << 8);
        for (int b = 0; b < 8; b++) {
            crc = (crc & 0x8000) ? (uint16_t)((crc << 1) ^ 0x1021) : (uint16_t)(crc << 1);
        }
    }
    return crc;
}

/* COBS as pinned in section 2: blocks end at each 0x00 and after 254 non-zero bytes; no code byte after a final
 * 254-byte block; a frame that ends in 0x00 gets a final empty block (01). */
size_t rzl_cobs_encode(const uint8_t *raw, size_t n, uint8_t *out)
{
    size_t o = 0;
    size_t i = 0;
    while (i < n) {
        size_t limit = (n - i > 254) ? i + 254 : n;
        size_t j = i;
        while (j < limit && raw[j] != 0) {
            j++;
        }
        out[o++] = (uint8_t)(j - i + 1);
        memcpy(&out[o], &raw[i], j - i);
        o += j - i;
        if (j < limit) { /* stopped at a zero: it is this block's terminator */
            i = j + 1;
            if (i == n) {
                out[o++] = 1; /* the frame ends in 0x00: final empty block */
            }
        } else {
            i = limit; /* full 254-byte block or the final short block, no implied zero */
        }
    }
    return o;
}

int rzl_cobs_decode(const uint8_t *enc, size_t n, uint8_t *out, size_t out_cap)
{
    if (n == 0) {
        return -1;
    }
    size_t o = 0;
    size_t i = 0;
    while (i < n) {
        uint8_t code = enc[i];
        if (code == 0) {
            return -1;
        }
        size_t end = i + code;
        if (end > n) {
            return -1;
        }
        for (size_t k = i + 1; k < end; k++) {
            if (enc[k] == 0 || o >= out_cap) {
                return -1;
            }
            out[o++] = enc[k];
        }
        i = end;
        if (i < n && code != 0xFF) {
            if (o >= out_cap) {
                return -1;
            }
            out[o++] = 0; /* implied zero between blocks */
        }
    }
    return (int)o;
}

/* ------------------------------------------------------------------ writer */
void rzl_w_init(rzl_w_t *w, uint8_t *buf, size_t cap)
{
    w->p = buf;
    w->n = 0;
    w->cap = cap;
    w->overflow = false;
}

void rzl_put_bytes(rzl_w_t *w, const void *b, size_t len)
{
    if (w->overflow || len > w->cap - w->n) {
        w->overflow = true;
        return;
    }
    if (len) {
        memcpy(&w->p[w->n], b, len);
    }
    w->n += len;
}

static void put_le(rzl_w_t *w, uint64_t v, int bytes)
{
    uint8_t b[8];
    for (int i = 0; i < bytes; i++) {
        b[i] = (uint8_t)(v >> (8 * i));
    }
    rzl_put_bytes(w, b, (size_t)bytes);
}

void rzl_put_u8(rzl_w_t *w, uint8_t v) { put_le(w, v, 1); }
void rzl_put_u16(rzl_w_t *w, uint16_t v) { put_le(w, v, 2); }
void rzl_put_u32(rzl_w_t *w, uint32_t v) { put_le(w, v, 4); }
void rzl_put_u64(rzl_w_t *w, uint64_t v) { put_le(w, v, 8); }
void rzl_put_i32(rzl_w_t *w, int32_t v) { put_le(w, (uint32_t)v, 4); }

void rzl_put_f32(rzl_w_t *w, float v)
{
    uint32_t u;
    memcpy(&u, &v, sizeof u);
    put_le(w, u, 4);
}

void rzl_put_str8(rzl_w_t *w, const char *s)
{
    size_t len = strlen(s);
    if (len > 255) {
        len = 255;
        while (len > 0 && (((const uint8_t *)s)[len] & 0xC0) == 0x80) {
            len--; /* cut on a UTF-8 code point boundary */
        }
    }
    rzl_put_u8(w, (uint8_t)len);
    rzl_put_bytes(w, s, len);
}

void rzl_put_blob16(rzl_w_t *w, const uint8_t *b, uint16_t len)
{
    rzl_put_u16(w, len);
    rzl_put_bytes(w, b, len);
}

void rzl_payload_w(rzl_w_t *w, uint8_t *buf, size_t buf_cap)
{
    size_t cap = buf_cap - RZL_HEADER_LEN - RZL_CRC_LEN;
    rzl_w_init(w, buf + RZL_HEADER_LEN, cap > RZL_MAX_PAYLOAD ? RZL_MAX_PAYLOAD : cap);
}

size_t rzl_finish(uint8_t *buf, size_t payload_len, uint8_t type, uint16_t seq, uint8_t *wire)
{
    buf[0] = RZL_VER;
    buf[1] = type;
    buf[2] = (uint8_t)(seq & 0xFF);
    buf[3] = (uint8_t)(seq >> 8);
    size_t body = RZL_HEADER_LEN + payload_len;
    uint16_t crc = rzl_crc16(buf, body);
    buf[body] = (uint8_t)(crc & 0xFF); /* little-endian */
    buf[body + 1] = (uint8_t)(crc >> 8);
    size_t n = rzl_cobs_encode(buf, body + RZL_CRC_LEN, wire);
    wire[n++] = 0x00;
    return n;
}

/* ------------------------------------------------------------------ node -> PC messages (codec.py) */
void rzl_enc_hello(rzl_w_t *w, uint8_t proto, const char *fw, const char *node_id, uint64_t t_dev_us,
                   const rzl_stream_info_t *s, uint8_t n_s, const rzl_head_info_t *h, uint8_t n_h)
{
    rzl_put_u8(w, proto);
    rzl_put_str8(w, fw);
    rzl_put_str8(w, node_id);
    rzl_put_u64(w, t_dev_us);
    rzl_put_u8(w, n_s);
    for (uint8_t i = 0; i < n_s; i++) {
        rzl_put_u8(w, s[i].id);
        rzl_put_u8(w, s[i].n_ch);
        rzl_put_u32(w, s[i].nominal_hz);
        rzl_put_u8(w, s[i].bits);
        rzl_put_u8(w, s[i].clock);
        rzl_put_u16(w, s[i].fir_taps);
        rzl_put_u16(w, s[i].fir_delay);
    }
    rzl_put_u8(w, n_h);
    for (uint8_t i = 0; i < n_h; i++) {
        rzl_put_u8(w, h[i].port);
        rzl_put_blob16(w, h[i].descriptor, h[i].len);
    }
}

void rzl_enc_config(rzl_w_t *w, const rzl_stream_cfg_t *s, uint8_t n_s, uint8_t accel_range_g,
                    uint16_t status_period_ms)
{
    rzl_put_u8(w, n_s);
    for (uint8_t i = 0; i < n_s; i++) {
        rzl_put_u8(w, s[i].id);
        rzl_put_u8(w, s[i].n_ch);
        for (uint8_t c = 0; c < s[i].n_ch; c++) {
            rzl_put_u8(w, s[i].gain[c]);
            rzl_put_f32(w, s[i].scale[c]);
            rzl_put_u8(w, s[i].units[c]);
        }
    }
    rzl_put_u8(w, accel_range_g);
    rzl_put_u16(w, status_period_ms);
}

void rzl_enc_data(rzl_w_t *w, uint8_t stream, uint8_t n_ch, uint16_t n, uint64_t first_sample, uint64_t t_dev_us,
                  const int32_t *samples)
{
    rzl_put_u8(w, stream);
    rzl_put_u8(w, n_ch);
    rzl_put_u16(w, n);
    rzl_put_u64(w, first_sample);
    rzl_put_u64(w, t_dev_us);
    for (size_t i = 0; i < (size_t)n * n_ch; i++) {
        rzl_put_i32(w, samples[i]);
    }
}

void rzl_enc_status(rzl_w_t *w, const rzl_status_hdr_t *hdr, const rzl_stream_status_t *s, uint8_t n_s)
{
    rzl_put_u64(w, hdr->t_dev_us);
    rzl_put_u8(w, hdr->queue_fill);
    rzl_put_u8(w, hdr->sd_state);
    rzl_put_u32(w, hdr->sd_free_mb);
    rzl_put_u8(w, (uint8_t)hdr->rssi_dbm);
    rzl_put_u32(w, hdr->heap_free);
    rzl_put_u16(w, (uint16_t)hdr->temp_c_x10);
    rzl_put_u8(w, n_s);
    for (uint8_t i = 0; i < n_s; i++) {
        rzl_put_u8(w, s[i].id);
        rzl_put_u8(w, s[i].running);
        rzl_put_u64(w, s[i].produced);
        rzl_put_u64(w, s[i].device_dropped);
        rzl_put_u32(w, s[i].rate_mhz);
        rzl_put_u32(w, s[i].clipped);
        rzl_put_u64(w, s[i].win_first);
        rzl_put_u64(w, s[i].win_end);
        rzl_put_u64(w, s[i].win_device);
        rzl_put_u64(w, s[i].win_link);
    }
}

void rzl_enc_ack(rzl_w_t *w, uint16_t cmd_seq) { rzl_put_u16(w, cmd_seq); }

void rzl_enc_err(rzl_w_t *w, uint16_t cmd_seq, uint16_t code, const char *msg)
{
    rzl_put_u16(w, cmd_seq);
    rzl_put_u16(w, code);
    rzl_put_str8(w, msg);
}

void rzl_enc_pong(rzl_w_t *w, uint64_t host_t_us, uint64_t t_dev_us)
{
    rzl_put_u64(w, host_t_us);
    rzl_put_u64(w, t_dev_us);
}

/* ------------------------------------------------------------------ reader */
void rzl_r_init(rzl_r_t *r, const uint8_t *p, size_t n)
{
    r->p = p;
    r->n = n;
    r->pos = 0;
    r->short_ = false;
}

const uint8_t *rzl_get_bytes(rzl_r_t *r, size_t len)
{
    if (r->short_ || len > r->n - r->pos) {
        r->short_ = true;
        return NULL;
    }
    const uint8_t *p = &r->p[r->pos];
    r->pos += len;
    return p;
}

static uint64_t get_le(rzl_r_t *r, int bytes)
{
    const uint8_t *b = rzl_get_bytes(r, (size_t)bytes);
    uint64_t v = 0;
    if (b != NULL) {
        for (int i = bytes - 1; i >= 0; i--) {
            v = (v << 8) | b[i];
        }
    }
    return v;
}

uint8_t rzl_get_u8(rzl_r_t *r) { return (uint8_t)get_le(r, 1); }
uint16_t rzl_get_u16(rzl_r_t *r) { return (uint16_t)get_le(r, 2); }
uint32_t rzl_get_u32(rzl_r_t *r) { return (uint32_t)get_le(r, 4); }
uint64_t rzl_get_u64(rzl_r_t *r) { return get_le(r, 8); }

/* ------------------------------------------------------------------ receiver */
void rzl_rx_init(rzl_rx_t *rx)
{
    rx->len = 0;
    rx->discarding = false;
    rx->bad_frames = 0;
    rx->frames_ok = 0;
}

/* One chunk between delimiters: COBS, length 6..4102, CRC, ver (codec.decode_chunk). */
static bool rx_chunk(rzl_rx_t *rx, rzl_frame_t *f)
{
    int n = rzl_cobs_decode(rx->chunk, rx->len, rx->raw, sizeof rx->raw);
    if (n < RZL_MIN_RAW || n > RZL_MAX_RAW) {
        return false;
    }
    size_t body = (size_t)n - RZL_CRC_LEN;
    uint16_t crc = (uint16_t)(rx->raw[body] | (rx->raw[body + 1] << 8));
    if (crc != rzl_crc16(rx->raw, body) || rx->raw[0] != RZL_VER) {
        return false;
    }
    f->type = rx->raw[1];
    f->seq = (uint16_t)(rx->raw[2] | (rx->raw[3] << 8));
    f->payload = &rx->raw[RZL_HEADER_LEN];
    f->len = body - RZL_HEADER_LEN;
    return true;
}

size_t rzl_rx_feed(rzl_rx_t *rx, const uint8_t *data, size_t n, rzl_frame_t *f, bool *got)
{
    *got = false;
    size_t i = 0;
    while (i < n) {
        uint8_t b = data[i++];
        if (b != 0x00) {
            if (rx->discarding) {
                continue;
            }
            if (rx->len >= RZL_MAX_ENCODED) { /* more than 4119 bytes without a 0x00: one bad frame */
                rx->bad_frames++;
                rx->discarding = true;
                rx->len = 0;
                continue;
            }
            rx->chunk[rx->len++] = b;
            continue;
        }
        if (rx->discarding) { /* the 0x00 that ends an oversize run */
            rx->discarding = false;
            continue;
        }
        if (rx->len == 0) {
            continue; /* extra delimiter */
        }
        bool ok = rx_chunk(rx, f);
        rx->len = 0;
        if (!ok) {
            rx->bad_frames++;
            continue;
        }
        rx->frames_ok++;
        *got = true;
        return i;
    }
    return i;
}

bool rzl_parse_set(const uint8_t *p, size_t n, rzl_set_t *s)
{
    rzl_r_t r;
    rzl_r_init(&r, p, n);
    memset(s, 0, sizeof *s);
    s->key_len = rzl_get_u8(&r);
    s->key = rzl_get_bytes(&r, s->key_len);
    s->type = rzl_get_u8(&r);
    if (r.short_) {
        return false;
    }
    switch (s->type) {
    case RZL_SET_I32:
        s->i32 = (int32_t)rzl_get_u32(&r);
        break;
    case RZL_SET_F32: {
        uint32_t u = rzl_get_u32(&r);
        memcpy(&s->f32, &u, sizeof u);
        break;
    }
    case RZL_SET_STR8:
        s->bytes_len = rzl_get_u8(&r);
        s->bytes = rzl_get_bytes(&r, s->bytes_len);
        break;
    case RZL_SET_BLOB16:
        s->bytes_len = rzl_get_u16(&r);
        s->bytes = rzl_get_bytes(&r, s->bytes_len);
        break;
    default:
        return false; /* unknown value type: codec.py raises CodecError -> ERR 2 */
    }
    return !r.short_;
}
