/*
 * DRDY edge classifier (see rz_drdy.h).
 */
#include "rz_drdy.h"

void rz_drdy_init(rz_drdy_t *d, int64_t period_us)
{
    d->period_us = period_us;
    rz_drdy_reset(d);
}

void rz_drdy_reset(rz_drdy_t *d)
{
    d->last = 0;
    d->prev = 0;
    d->have_last = false;
    d->have_prev = false;
}

/* Nearest whole number of periods in gap g (0 for a negative gap), and the distance from it. */
static int64_t periods(const rz_drdy_t *d, int64_t g, int64_t *off)
{
    int64_t m = g > 0 ? (2 * g + d->period_us) / (2 * d->period_us) : 0;
    int64_t o = g - m * d->period_us;
    *off = o < 0 ? -o : o;
    return m;
}

static void take(rz_drdy_t *d, int64_t t_us)
{
    d->prev = d->last;
    d->have_prev = d->have_last;
    d->last = t_us;
    d->have_last = true;
}

rz_drdy_kind_t rz_drdy_edge(rz_drdy_t *d, int64_t t_us, uint32_t *skipped)
{
    *skipped = 0;
    if (!d->have_last) {
        take(d, t_us);
        return RZ_DRDY_CONV;
    }
    int64_t off;
    int64_t m = periods(d, t_us - d->last, &off);
    if (m >= 2) {
        *skipped = m - 1 > (int64_t)UINT32_MAX ? UINT32_MAX : (uint32_t)(m - 1);
        take(d, t_us);
        return RZ_DRDY_CONV;
    }
    if (m == 1 && 3 * off <= d->period_us) { /* |g - T| <= T / 3, no rounding */
        take(d, t_us);
        return RZ_DRDY_CONV;
    }
    if (d->have_prev) {
        int64_t off_last, off_this;
        int64_t m_last = periods(d, d->last - d->prev, &off_last);
        int64_t m_this = periods(d, t_us - d->prev, &off_this);
        if (m_last >= 1 && m_this == m_last && off_this < off_last) {
            d->last = t_us; /* the previous "conversion" was the pulse */
            return RZ_DRDY_MOVED;
        }
    }
    return RZ_DRDY_PULSE;
}

uint32_t rz_drdy_classify(rz_drdy_t *d, int64_t *t, uint32_t *skip, uint32_t n)
{
    uint32_t n_real = 0;
    for (uint32_t i = 0; i < n; i++) {
        uint32_t s;
        rz_drdy_kind_t k = rz_drdy_edge(d, t[i], &s);
        if (k == RZ_DRDY_CONV) {
            skip[n_real] = s;
            t[n_real++] = t[i];
        } else if (k == RZ_DRDY_MOVED && n_real > 0) {
            t[n_real - 1] = t[i]; /* (moved from an earlier wake-up: that conversion is already handled) */
        }
    }
    return n_real;
}

void rz_drdy_unclaim(rz_drdy_t *d)
{
    d->last = d->prev;
    d->have_last = d->have_prev;
    d->have_prev = false;
}

bool rz_drdy_leftover(rz_drdy_lo_t *lo, uint32_t n_pulses)
{
    bool left = n_pulses > lo->expect;
    lo->expect = n_pulses >= lo->expect ? 0 : (uint8_t)(lo->expect - n_pulses);
    if (left) {
        lo->expect = 1; /* the drain read itself makes a pulse if yet another frame is queued */
    }
    return left;
}

void rz_drdy_leftover_reads(rz_drdy_lo_t *lo, uint32_t n_read)
{
    if (n_read >= RZ_DRDY_FIFO && lo->expect < 2) {
        lo->expect++;
    }
}
