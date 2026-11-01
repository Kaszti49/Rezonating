/*
 * D-016 decimator, a C port of rezonating_ml.dsp.Decimator2 (see rz_decim.h). Compile with -ffp-contract=off.
 */
#include "rz_decim.h"

#include <math.h>
#include <string.h>

/* DECIM_FIR_TAPS of ml/src/rezonating_ml/dsp.py, copied verbatim (float32). */
const float rz_decim_taps[RZ_DECIM_TAPS] = {
    -1.9752368e-05f, 1.0312901e-07f,  7.2250514e-05f, -2.4318265e-07f, -0.00019518388f, 6.1545717e-07f,
    0.00044213777f,  -1.1609376e-06f, -0.0008901965f, 2.0815464e-06f,  0.001644132f,    -3.310028e-06f,
    -0.0028402489f,  5.0157882e-06f,  0.0046535046f,  -7.0589617e-06f, -0.0073105283f,  9.51753e-06f,
    0.011121361f,    -1.2161764e-05f, -0.016553467f,  1.4952673e-05f,  0.024419704f,    -1.7579334e-05f,
    -0.036403637f,   1.9965431e-05f,  0.056866363f,   -2.1782995e-05f, -0.101892754f,   2.2997356e-05f,
    0.31688485f,     0.49997902f,     0.31688485f,    2.2997356e-05f,  -0.101892754f,   -2.1782995e-05f,
    0.056866363f,    1.9965431e-05f,  -0.036403637f,  -1.7579334e-05f, 0.024419704f,    1.4952673e-05f,
    -0.016553467f,   -1.2161764e-05f, 0.011121361f,   9.51753e-06f,    -0.0073105283f,  -7.0589617e-06f,
    0.0046535046f,   5.0157882e-06f,  -0.0028402489f, -3.310028e-06f,  0.001644132f,    2.0815464e-06f,
    -0.0008901965f,  -1.1609376e-06f, 0.00044213777f, 6.1545717e-07f,  -0.00019518388f, -2.4318265e-07f,
    7.2250514e-05f,  1.0312901e-07f,  -1.9752368e-05f,
};

void rz_decim_init(rz_decim_t *d, int n_ch)
{
    memset(d, 0, sizeof *d); /* history before raw index 0 is zeros (start-up, not lost); last good = 0 */
    d->n_ch = n_ch > RZ_DECIM_MAXCH ? RZ_DECIM_MAXCH : n_ch;
}

bool rz_decim_push(rz_decim_t *d, const int32_t *x, bool valid, float *y, bool *out_valid)
{
    uint64_t n = d->n_in++;
    d->pos = (d->pos + 1) % RZ_DECIM_TAPS;
    for (int c = 0; c < d->n_ch; c++) {
        if (valid) {
            d->last_good[c] = (float)x[c]; /* 24-bit codes are exact in float32 */
        }
        d->hist[c][d->pos] = d->last_good[c]; /* a lost sample holds the previous good one (0 if none yet) */
    }
    if (!valid) {
        d->lost_until = n + RZ_DECIM_TAPS; /* outputs at raw n .. n + 62 have it in their window */
    }
    if ((n & 1u) == 0) {
        return false; /* keep odd raw indices only: decimated[k] = y[2k + 1] */
    }
    for (int c = 0; c < d->n_ch; c++) {
        /* acc += h[j] * x[n - j], j ascending, float32 multiply then float32 add (dsp.py, no contraction) */
        float acc = 0.0f;
        int p = d->pos;
        for (int j = 0; j < RZ_DECIM_TAPS; j++) {
            float prod = rz_decim_taps[j] * d->hist[c][p];
            acc = acc + prod;
            p = (p == 0) ? RZ_DECIM_TAPS - 1 : p - 1;
        }
        y[c] = acc;
    }
    *out_valid = n >= d->lost_until;
    return true;
}

int32_t rz_decim_code(float y)
{
    double v = (double)y;
    double r = (v >= 0.0) ? floor(v + 0.5) : ceil(v - 0.5);
    if (r > 8388607.0) {
        return 8388607;
    }
    if (r < -8388608.0) {
        return -8388608;
    }
    return (int32_t)r;
}
