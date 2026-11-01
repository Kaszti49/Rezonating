/*
 * D-016 decimator for the bench link's adc_dec stream: 63-tap FIR low-pass, keep the outputs at odd raw indices
 * (2 kSPS -> 1 kSPS), hold-previous for lost raw samples, round half away from zero and saturate to 24 bits.
 *
 * A C port of rezonating_ml.dsp.Decimator2 + to_adc_dec_codes (ml/src/rezonating_ml/dsp.py), checked against
 * ml/tests/vectors/decimator_fir.json by test_host/. Build rz_decim.c with -ffp-contract=off (no fused multiply-add),
 * as dsp.py requires.
 *
 * Portable C99: no ESP-IDF headers.
 */
#pragma once

#include <stdbool.h>
#include <stdint.h>

#define RZ_DECIM_TAPS  63
#define RZ_DECIM_DELAY 31 /* (taps - 1) / 2 raw samples */
#define RZ_DECIM_MAXCH 2

extern const float rz_decim_taps[RZ_DECIM_TAPS];

typedef struct {
    float hist[RZ_DECIM_MAXCH][RZ_DECIM_TAPS]; /* circular: the last 63 raw samples after hold-previous */
    float last_good[RZ_DECIM_MAXCH];
    int n_ch;
    int pos;            /* where the newest sample is in hist */
    uint64_t n_in;      /* raw samples consumed (good or lost) */
    uint64_t lost_until; /* raw index + 1 of the newest lost sample after which a window is clean: an output at raw
                            n is valid when n >= lost_until; 0 = none lost yet */
} rz_decim_t;

void rz_decim_init(rz_decim_t *d, int n_ch);

/* Push raw sample n = d->n_in (x: n_ch values; ignored when !valid). When n is odd, writes the FIR output for
 * decimated index k = (n - 1) / 2 to y (n_ch floats), sets *out_valid (false when any raw sample in the FIR window
 * n - 62 .. n was lost) and returns true. */
bool rz_decim_push(rz_decim_t *d, const int32_t *x, bool valid, float *y, bool *out_valid);

/* to_adc_dec_codes: round to nearest, halves away from zero (in double, exact for every float32), saturate to
 * -8388608 .. 8388607. */
int32_t rz_decim_code(float y);
