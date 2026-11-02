/*
 * DRDY edge classifier for the bench reader: which DRDY falling edges are conversions (sample intervals) and which
 * are the narrow pulse the ADS131M02 sends after the first of two queued frames is read (SBAS853A 8.5.1.9.1,
 * DRDY_FMT = 0), and how many sample intervals passed with no edge at all.
 *
 * Conversion edges sit on a grid one data period T apart (plus interrupt jitter); a narrow pulse comes when the
 * reader does a double read, anywhere between two conversion edges, and at most once per period (a double read
 * needs two new conversions). Rule, with the gap g from the previous conversion edge and m = round(g / T):
 *   - m == 1 and |g - T| <= T / 3: a conversion;
 *   - m >= 2: a conversion after m - 1 sample intervals with no conversion edge (an edge the interrupt did not see,
 *     DRDY stopped, or a conversion given back by rz_drdy_unclaim); those m - 1 are reported as skipped, so the raw
 *     index advances by m (PROTOCOL.md 4.4: a gap of g periods means g - 1 indices were skipped);
 *   - anything else: the narrow pulse. If that edge fits the grid (from the conversion before the previous one)
 *     better than the previous conversion edge did, the previous one was the pulse: the conversion moves to this
 *     edge (RZ_DRDY_MOVED; the count is unchanged).
 * So a pulse in the middle of a period never counts, and one within T / 3 of the next grid point is counted in place
 * of the conversion that follows it. If the read for an edge taken as a conversion finds no new data,
 * rz_drdy_unclaim puts the reference back; when that was a real conversion (a new one landed between the wake-up
 * and the first SPI read, so the FIFO moved on), the next conversion edge is two periods away and reports one
 * skipped interval, which puts the index back in step. The reader applies an edge's skipped intervals only after
 * its read turned out not to be stale (a given-back edge's skip comes again with the next conversion).
 *
 * Host simulation (test_host/, reads take time, the FIFO is sampled at each read's start): the final index offset
 * is 0 and at most a few reads per event land on a neighbouring index, with interrupt latency (spread or rare
 * spikes) up to 100 us, +-1.65 % rate error, lost interrupt edges and CRC errors. Latency of 130 us and more can
 * shift the index by one for good (a late conversion edge moves the grid): the classifier relies on the DRDY
 * interrupt latency on core 1 staying well under that.
 *
 * Portable C99: no ESP-IDF headers (host-tested in test_host/).
 */
#pragma once

#include <stdbool.h>
#include <stdint.h>

#define RZ_DRDY_FIFO 2 /* the ADS131M02 output FIFO holds two samples per channel (8.5.1.9.1) */

typedef enum {
    RZ_DRDY_PULSE = 0, /* the narrow pulse: no conversion */
    RZ_DRDY_CONV,      /* a conversion (possibly after skipped intervals) */
    RZ_DRDY_MOVED,     /* the narrow pulse, and the previous conversion's DRDY time is this edge's */
} rz_drdy_kind_t;

typedef struct {
    int64_t period_us; /* nominal data period */
    int64_t last;      /* DRDY time of the newest conversion edge */
    int64_t prev;      /* the one before it (for RZ_DRDY_MOVED and rz_drdy_unclaim) */
    bool have_last;
    bool have_prev;
} rz_drdy_t;

/* No reference yet: the next edge counts as a conversion (with no skipped intervals). */
void rz_drdy_init(rz_drdy_t *d, int64_t period_us);

/* Forget the reference (start-up, or after DRDY times were overwritten): the next edge counts as a conversion. */
void rz_drdy_reset(rz_drdy_t *d);

/* Classify one edge at time t_us (edges in order). For RZ_DRDY_CONV, *skipped = the sample intervals before it that
 * had no conversion edge (0 normally); 0 for the other kinds. */
rz_drdy_kind_t rz_drdy_edge(rz_drdy_t *d, int64_t t_us, uint32_t *skipped);

/* Classify n edges in order and compact the conversion edges' times to the front of t, with skip[i] = the skipped
 * intervals just before conversion i (skip has room for n). Returns how many conversions there are. The newest
 * RZ_DRDY_FIFO of them are still in the ADC's FIFO; the older ones were overwritten (missed). */
uint32_t rz_drdy_classify(rz_drdy_t *d, int64_t *t, uint32_t *skip, uint32_t n);

/* How many of n_real conversions the reader can still read (the rest are missed). */
static inline uint32_t rz_drdy_n_read(uint32_t n_real) { return n_real < RZ_DRDY_FIFO ? n_real : RZ_DRDY_FIFO; }

/* The read for the newest conversion edge found no new data: it was the narrow pulse after all, or the FIFO had
 * already moved on. The reference goes back to the conversion edge before it. A second unclaim in a row drops the
 * reference. */
void rz_drdy_unclaim(rz_drdy_t *d);

/*
 * Left-over frame detector. Every read that leaves a frame in the FIFO makes one narrow pulse; normally that is only
 * the first read of a double read. If a conversion edge was not seen (or a pulse was counted in its place) the reader
 * reads one frame per conversion while the FIFO holds two, so every frame it reads is the previous conversion's, and
 * every read makes a pulse that no double read explains. Seeing such a pulse, the reader reads the left-over frame
 * and drops it (its index already went to the frame before it), which puts it back in step.
 */
typedef struct {
    uint8_t expect; /* pulses the recent reads explain */
} rz_drdy_lo_t;

static inline void rz_drdy_lo_init(rz_drdy_lo_t *lo) { lo->expect = 0; }

/* n_pulses = narrow pulses (RZ_DRDY_PULSE or RZ_DRDY_MOVED) among this wake-up's edges. True: read one frame now,
 * before this wake-up's reads, and drop it. */
bool rz_drdy_leftover(rz_drdy_lo_t *lo, uint32_t n_pulses);

/* After this wake-up's reads: n_read frames read back to back (a double read explains one pulse). */
void rz_drdy_leftover_reads(rz_drdy_lo_t *lo, uint32_t n_read);
