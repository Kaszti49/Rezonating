// REZON fall-score weights. Written by tools/fit from 152 events: 7 falls, 145 not-falls.
// FITTED: regularised logistic regression, sign-constrained.
// z = (x - mu) / sd, score = w . z + bias. Feature order: lnPeak lnEnergy dur nSub rise decay bandRatio centroid relPeak
#pragma once
#include "rezon_core.h"
namespace rezon {
const Weights DEFAULT_WEIGHTS = {
  /* mu    */ { -3.19625f, -10.50946f, 0.11586f, 1.00000f, 0.09546f, 0.06990f, -0.84875f, 27.97428f, -0.70700f },
  /* sd    */ { 1.02225f, 2.98025f, 0.06753f, 1.00000f, 0.07411f, 0.03888f, 2.09263f, 10.49833f, 1.10104f },
  /* w     */ { 1.44857f, 0.94879f, 0.55827f, 0.00000f, -0.33705f, 0.83838f, -0.18063f, 0.24524f, 1.10865f },
  /* bias  */ -6.99261f,
  /* sigMu */ { 0.11155f, 28.18369f, -0.89491f, 0.06614f, 0.08355f, 0.21980f, 0.15625f, 0.14112f, 0.11575f, 0.11197f, 0.08817f, 0.08951f, 0.07743f },
  /* sigSd */ { 0.07203f, 10.67437f, 2.12892f, 0.05863f, 0.05464f, 0.15021f, 0.13449f, 0.12384f, 0.11454f, 0.10175f, 0.09915f, 0.08865f, 0.07959f },
};
}
