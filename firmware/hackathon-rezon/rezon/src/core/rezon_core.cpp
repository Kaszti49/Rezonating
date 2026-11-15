// REZON detection core, see rezon_core.h. No Arduino includes.
#include "rezon_core.h"
#include "rezon_weights.h"
#include <math.h>
#include <string.h>

namespace rezon {

const char *const FEAT_NAME[NFEAT] = { "lnPeak", "lnEnergy", "dur", "nSub", "rise", "decay", "bandRatio", "centroid", "relPeak" };
const char *const CLS_NAME[8] = { "noise", "step", "impact", "FALL", "ring", "bystander", "floor", "newstep" };

static const float BAND_LO[NBANDS] = { 10.f, 20.f, 30.f, 45.f };
static const float BAND_HI[NBANDS] = { 20.f, 30.f, 45.f, 65.f };
static const float BAND_FC[NBANDS] = { 14.14f, 24.49f, 36.74f, 54.08f };   // geometric centres
static const uint32_t WARMUP_MS = 1500;   // filters and background followers settle: no events before this
#define FRM(f) fr_[(f) % NFRAMES]

static inline float maxf(float a, float b) { return a > b ? a : b; }
static inline float minf(float a, float b) { return a < b ? a : b; }
static inline float clampf(float x, float lo, float hi) { return x < lo ? lo : (x > hi ? hi : x); }

// ---------------------------------------------------------------- layer 1: signal
Detector::Biquad Detector::mk(bool hp, float f0, float q) {
  const float w = 2.f * 3.14159265f * f0 / FS, c = cosf(w), al = sinf(w) / (2.f * q), a0 = 1.f + al;
  Biquad k;
  if (hp) { k.b0 = (1 + c) / 2 / a0; k.b1 = -(1 + c) / a0; k.b2 = k.b0; }
  else    { k.b0 = (1 - c) / 2 / a0; k.b1 = (1 - c) / a0;  k.b2 = k.b0; }
  k.a1 = -2 * c / a0; k.a2 = (1 - al) / a0; k.z1 = k.z2 = 0;
  return k;
}

Detector::Detector() { wts = DEFAULT_WEIGHTS; reset(); }

void Detector::reset() {
  // 4th-order Butterworth on each side = two biquads with Q 0.5412 and 1.3066
  bpI_[0] = mk(true, 10, 0.5412f); bpI_[1] = mk(true, 10, 1.3066f); bpI_[2] = mk(false, 45, 0.5412f); bpI_[3] = mk(false, 45, 1.3066f);
  bpS_[0] = mk(true, 18, 0.5412f); bpS_[1] = mk(true, 18, 1.3066f); bpS_[2] = mk(false, 60, 0.5412f); bpS_[3] = mk(false, 60, 1.3066f);
  for (int k = 0; k < NBANDS; k++) { bank_[k][0] = mk(true, BAND_LO[k], 0.7071f); bank_[k][1] = mk(false, BAND_HI[k], 0.7071f); }
  memset(aleW_, 0, sizeof aleW_); memset(aleBuf_, 0, sizeof aleBuf_); alePos_ = 0;
  dcInit_ = false; dc_ = 0; scale_ = 0; scaleGain_ = 0; scaleSens_ = 0;
  v_ = yi_ = ys_ = 0; eI2_ = eS2_ = 0;
  memset(fr_, 0, sizeof fr_); nFrames_ = 0; memset(&acc_, 0, sizeof acc_); accN_ = 0;
  memset(vS_, 0, sizeof vS_); memset(vI_, 0, sizeof vI_); vPos_ = 0; vSsum_ = vIsum_ = 0;
  bgS_ = bgI_ = 0.01f * 0.01f / 2; for (int k = 0; k < NBANDS; k++) bgBand_[k] = 0; thS_ = cfg.stepMin;
  open_ = impactSized_ = earlySent_ = due_ = false; fOn_ = fPk_ = 0; pkES_ = pkEI_ = pkYI_ = bgAtOn_ = levelAtOn_ = impThAtOn_ = 0; quiet_ = 0;
  memset(lvT_, 0, sizeof lvT_); memset(lvP_, 0, sizeof lvP_); lvPos_ = 0;
  lastPkMs_ = 0; dueOn_ = false;
  nextId_ = 1; memset(tr_, 0, sizeof tr_);
  fallActive_ = false; ringDone_ = true; fallT_ = 0; lastImpactT_ = 0; lastImpactPk_ = 0;
  qHead_ = qN_ = 0; n_ = 0;
}

// Adaptive line enhancer: an LMS predictor learns whatever is steady (hum tones) from samples that are at least 25 ms old.
// The prediction error is what is NOT steady: footsteps stay, hum goes.
float Detector::ale(float x) {
  const int L = 48, D = 25; const float mu = 0.004f;
  alePos_ = (alePos_ - 1) & 127; aleBuf_[alePos_] = x;
  float p = 0, uu = 0;
  for (int i = 0; i < L; i++) { const float u = aleBuf_[(alePos_ + D + i) & 127]; p += aleW_[i] * u; uu += u * u; }
  const float e = x - p, g = mu * e / (uu + 1e-12f);
  for (int i = 0; i < L; i++) aleW_[i] += g * aleBuf_[(alePos_ + D + i) & 127];
  return e;
}

float Detector::background() const { return sqrtf(2.f * bgS_); }

// Step level for the normalised rule: the second-loudest step-like event from levelMs to levelGapMs ago. The second, so that
// one odd loud step does not lift it; one event alone counts as it is; none at all falls back to stepRef. The last second is left
// out because a fall often begins with smaller hits (stumble, knee) that would otherwise raise the level just before the big one.
float Detector::level() const {
  float a = 0, b = 0; int c = 0;
  for (int i = 0; i < NLEVEL; i++) {
    if (!lvT_[i] || n_ - lvT_[i] > (uint32_t)cfg.levelMs || n_ - lvT_[i] < (uint32_t)cfg.levelGapMs) continue;
    c++; const float p = lvP_[i];
    if (p > a) { b = a; a = p; } else if (p > b) b = p;
  }
  return c == 0 ? cfg.stepRef : (c == 1 ? a : b);
}

float Detector::impactThreshold() const {
  return cfg.rule == 1 ? maxf(cfg.impactMin, cfg.relMin * level()) : cfg.impactMin;
}

// How long the impact envelope stays at or above holdFrac of its own peak, from 300 ms before to 600 ms after the peak frame.
// It does not change when the whole event is scaled, so a far fall and a near fall give the same number.
float Detector::holdOf(uint32_t fPk, uint32_t fEnd) const {
  const uint32_t pre = 300 / HOP, post = 600 / HOP;
  uint32_t a = fPk >= pre ? fPk - pre : 0, b = fPk + post < fEnd ? fPk + post : fEnd;
  if (nFrames_ - a >= (uint32_t)NFRAMES) a = nFrames_ - NFRAMES + 1;          // older frames are overwritten already
  float pk = 0;
  for (uint32_t f = a; f <= b; f++) if (FRM(f).eI > pk) pk = FRM(f).eI;
  if (pk <= 0) return 0;
  int k = 0;
  for (uint32_t f = a; f <= b; f++) if (FRM(f).eI >= cfg.holdFrac * pk) k++;
  return k * HOP / 1000.f;
}

int Detector::push(int32_t counts) {
  if (cfg.gain != scaleGain_ || cfg.sens != scaleSens_) {       // counts -> mm/s: 1.2 V reference, 24 bit, gain, mV per mm/s
    scaleGain_ = cfg.gain; scaleSens_ = cfg.sens; scale_ = 1200.f / (float)cfg.gain / 8388608.f / cfg.sens;
  }
  const float c = (float)counts;
  if (!dcInit_) { dc_ = c; dcInit_ = true; }
  dc_ += (c - dc_) * 0.002f;                                     // one-pole high-pass, corner about 0.3 Hz
  const float v = (c - dc_) * scale_;
  v_ = v;
  float yi = v; for (int i = 0; i < 4; i++) yi = run(bpI_[i], yi);
  float ys = v; for (int i = 0; i < 4; i++) ys = run(bpS_[i], ys);
  ys = ale(ys);
  yi_ = yi; ys_ = ys;
  eI2_ += (yi * yi - eI2_) / 15.f; eS2_ += (ys * ys - eS2_) / 15.f;   // 15 ms mean square
  const float eI = sqrtf(2.f * eI2_), eS = sqrtf(2.f * eS2_);          // sqrt(2) turns the RMS of a sine into its peak

  acc_.sI2 += yi * yi; acc_.sS2 += ys * ys;
  const float ai = fabsf(yi), as = fabsf(ys);
  if (ai > acc_.pkI) acc_.pkI = ai;
  if (as > acc_.pkS) acc_.pkS = as;
  if (eI > acc_.eI) acc_.eI = eI;
  if (eS > acc_.eS) acc_.eS = eS;
  for (int k = 0; k < NBANDS; k++) { float y = run(bank_[k][0], v); y = run(bank_[k][1], y); acc_.b[k] += y * y; }
  n_++;
  if (++accN_ == HOP) { frameDone(); memset(&acc_, 0, sizeof acc_); accN_ = 0; }
  return qN_;
}

void Detector::emit(NoteKind k, float value, const Event *e) {
  if (qN_ == 8) { qHead_ = (qHead_ + 1) & 7; qN_--; }            // queue full: drop the oldest
  Note &o = q_[(qHead_ + qN_) & 7]; qN_++;
  o.kind = k; o.t = n_; o.value = value;
  if (e) o.ev = *e; else memset(&o.ev, 0, sizeof o.ev);
}
bool Detector::poll(Note &out) {
  if (!qN_) return false;
  out = q_[qHead_]; qHead_ = (qHead_ + 1) & 7; qN_--;
  return true;
}

// ---------------------------------------------------------------- layer 2: events

void Detector::frameDone() {
  const uint32_t f = nFrames_;
  FRM(f) = acc_; nFrames_++;
  const Frame &fr = FRM(f);
  // 50 ms variance of both paths (the filtered signals have zero mean, so variance = mean square)
  vSsum_ += fr.sS2 - vS_[vPos_]; vS_[vPos_] = fr.sS2;
  vIsum_ += fr.sI2 - vI_[vPos_]; vI_[vPos_] = fr.sI2;
  vPos_ = (vPos_ + 1) % 10;
  const float Vs = maxf(vSsum_, 0) / 50.f, Vi = maxf(vIsum_, 0) / 50.f;
  // background: follows the quiet moments (drops in about 0.1 s, rises over about 2 s)
  const bool warm = n_ >= WARMUP_MS;
  const float cd = warm ? 0.049f : 0.2f, cu = warm ? 0.0025f : 0.2f;
  bgS_ += (Vs - bgS_) * (Vs < bgS_ ? cd : cu);
  bgI_ += (Vi - bgI_) * (Vi < bgI_ ? cd : cu);
  if (!open_) for (int k = 0; k < NBANDS; k++) bgBand_[k] += (fr.b[k] / HOP - bgBand_[k]) * (warm ? 0.01f : 0.2f);

  due_ = stepDue();
  thS_ = maxf(cfg.stepMin, sqrtf(cfg.kOn * 2.f * bgS_)) * (due_ ? cfg.dueDrop : 1.f);
  if ((f % 10) == 0) expire();
  if (!warm) return;

  const uint32_t nowMs = n_;
  if (!open_) {
    // A start needs a RISE: the last 20 ms must carry clearly more power than the quietest 20 ms of the 40-140 ms before.
    // A decaying floor ring therefore never starts an event, a step on top of it does.
    float pS = 0, pI = 0, refS = 1e30f, refI = 1e30f;
    for (int i = 0; i < 4; i++) { const Frame &a = FRM(f - i); pS += a.sS2; pI += a.sI2; }
    if (f >= 32) for (int k = 8; k <= 24; k += 4) {
      float s = 0, q = 0; for (int i = 0; i < 4; i++) { const Frame &a = FRM(f - k - i); s += a.sS2; q += a.sI2; }
      if (s < refS) refS = s;
      if (q < refI) refI = q;
    } else refS = refI = 0;
    const float stat = cfg.segMode == 0 ? sqrtf(2.f * Vs) : fr.eS;
    const bool startS = stat > thS_ && pS > cfg.riseK * refS;
    const float impTh = impactThreshold();
    const bool startI = fr.eI > 0.7f * impTh && pI > cfg.riseK * refI;
    const bool refr = cfg.segMode == 1 && lastPkMs_ && nowMs - lastPkMs_ < (uint32_t)cfg.refractMs && !startI;
    if ((startS || startI) && !refr) {
      open_ = true; impactSized_ = earlySent_ = false; quiet_ = 0; dueOn_ = due_ && !startI;
      fOn_ = f; fPk_ = f; pkES_ = fr.eS; pkEI_ = fr.eI; pkYI_ = fr.pkI; bgAtOn_ = sqrtf(2.f * bgS_);
      levelAtOn_ = level(); impThAtOn_ = impTh;                    // frozen for the whole event
    }
    return;
  }
  // event is open
  if (fr.eI > pkEI_) { pkEI_ = fr.eI; if (impactSized_ || fr.pkI >= impThAtOn_) fPk_ = f; }
  if (fr.eS > pkES_) { pkES_ = fr.eS; if (!impactSized_ && fr.pkI < impThAtOn_) fPk_ = f; }
  if (fr.pkI > pkYI_) pkYI_ = fr.pkI;
  if (!impactSized_ && pkYI_ >= impThAtOn_) impactSized_ = true;
  if (impactSized_ && !earlySent_ && pkYI_ >= cfg.walkerMargin * walkerSum()) { earlySent_ = true; emit(N_IMPACT_EARLY, pkYI_, nullptr); }

  const uint32_t durMs = (f - fOn_ + 1) * HOP;
  bool close = false, cut = false;
  if (impactSized_) {
    // an impact is analysed over a fixed window from its onset (sub-impacts, decay), or until the floor is quiet again
    if (Vs < cfg.kOff * bgS_ && fr.eI < 0.1f * pkEI_) quiet_++; else quiet_ = 0;
    if (quiet_ >= 6) close = true;
    // rule 1 also needs 600 ms after the peak for the hold measure
    else if ((durMs >= (uint32_t)cfg.impactWinMs && (cfg.rule == 0 || (f - fPk_) * HOP >= 600)) || durMs >= (uint32_t)cfg.maxEventMs) { close = true; cut = true; }
  } else if (cfg.segMode == 0) {
    if (Vs < cfg.kOff * bgS_) quiet_++; else quiet_ = 0;
    if (quiet_ >= 2) close = true;
    else if (durMs >= (uint32_t)cfg.maxEventMs) { close = true; cut = true; }
  } else {
    if (fr.eS < cfg.endFrac * pkES_ && fr.eI < cfg.endFrac * pkEI_) close = true;
    else if ((f - fPk_) * HOP > (uint32_t)cfg.maxStepMs) { close = true; cut = true; }
  }
  if (close) closeEvent(f, cut);
}

void Detector::closeEvent(uint32_t fEnd, bool cut) {
  open_ = false;
  Event e; memset(&e, 0, sizeof e);
  e.id = nextId_++; e.track = -1; e.bg = bgAtOn_; e.level = levelAtOn_;
  if (cut) e.flags |= FL_CUT;
  if (dueOn_) e.flags |= FL_DUE;
  const uint32_t pre = fOn_ >= 6 ? 6 : fOn_;                     // 30 ms before the trigger: the rise started there
  uint32_t f0 = fOn_ - pre;
  if (fEnd - f0 >= (uint32_t)NFRAMES) f0 = fEnd - NFRAMES + 1;
  e.tOn = fOn_ * HOP; e.tPk = fPk_ * HOP; e.tEnd = (fEnd + 1) * HOP;
  lastPkMs_ = e.tPk;
  features(e, f0, fEnd);
  e.rel = e.peakI / maxf(levelAtOn_, 1e-6f);
  e.hold = impactSized_ ? holdOf(fPk_, fEnd) : 0;
  classify(e);
  // every step-sized event that is not ringing or noise feeds the step level (impact-sized ones never do)
  if (!(e.flags & FL_GATE_PEAK) && e.cls != C_RING && e.cls != C_NOISE) { lvT_[lvPos_] = e.tPk ? e.tPk : 1; lvP_[lvPos_] = e.peakI; lvPos_ = (lvPos_ + 1) % NLEVEL; }
  emit(N_EVENT, 0, &e);
  if (e.cls == C_FALL) emit(N_FALL, e.score, &e);
}

// ---------------------------------------------------------------- layer 3: features
// Shape numbers of one envelope: duration that holds the middle 90 % of the energy, rise 10 % -> peak, decay peak -> 30 %,
// and the energy split into 8 equal time slices. None of them changes when the whole event is scaled (distance).
namespace {
struct Shape { float dur, rise, decay, shape[NSHAPE]; uint32_t iMax; float max; };
}

void Detector::features(Event &e, uint32_t f0, uint32_t f1) {
  const int N = (int)(f1 - f0 + 1);
  static float sm[NFRAMES];
  float sumI2 = 0, band[NBANDS] = { 0, 0, 0, 0 };
  e.peakI = e.peakS = 0;
  for (uint32_t f = f0; f <= f1; f++) {
    const Frame &a = FRM(f);
    sumI2 += a.sI2; for (int k = 0; k < NBANDS; k++) band[k] += a.b[k];
    if (a.pkI > e.peakI) e.peakI = a.pkI;
    if (a.pkS > e.peakS) e.peakS = a.pkS;
  }
  auto shapeOf = [&](bool stepPath) {
    Shape s; memset(&s, 0, sizeof s);
    const float bgp = (stepPath ? bgS_ : bgI_) * HOP;
    float tot = 0;
    for (uint32_t f = f0; f <= f1; f++) {
      const Frame &a = FRM(f); const float en = stepPath ? a.eS : a.eI;
      if (en > s.max) { s.max = en; s.iMax = f; }
      tot += maxf((stepPath ? a.sS2 : a.sI2) - bgp, 0);
    }
    uint32_t i10 = s.iMax, i30 = f1;
    for (uint32_t f = f0; f <= s.iMax; f++) if ((stepPath ? FRM(f).eS : FRM(f).eI) >= 0.1f * s.max) { i10 = f; break; }
    for (uint32_t f = s.iMax + 1; f <= f1; f++) if ((stepPath ? FRM(f).eS : FRM(f).eI) < 0.3f * s.max) { i30 = f; break; }
    s.rise = (s.iMax - i10) * HOP / 1000.f; s.decay = (i30 - s.iMax) * HOP / 1000.f;
    uint32_t i05 = f0, i95 = f1; float cum = 0; bool got05 = false;
    if (tot > 0) for (uint32_t f = f0; f <= f1; f++) {
      const Frame &a = FRM(f); cum += maxf((stepPath ? a.sS2 : a.sI2) - bgp, 0);
      if (!got05 && cum >= 0.05f * tot) { i05 = f; got05 = true; }
      if (cum >= 0.95f * tot) { i95 = f; break; }
    }
    const int span = (int)(i95 - i05 + 1);
    s.dur = span * HOP / 1000.f;
    float st = 0;
    for (uint32_t f = i05; f <= i95; f++) {
      const Frame &a = FRM(f); const float p = maxf((stepPath ? a.sS2 : a.sI2) - bgp, 0);
      s.shape[(int)((f - i05) * NSHAPE / span)] += p; st += p;
    }
    if (st > 0) for (int i = 0; i < NSHAPE; i++) s.shape[i] /= st;
    return s;
  };
  const Shape si = shapeOf(false), ss = shapeOf(true);

  // sub-impacts: peaks of the 40 ms-smoothed impact envelope that reach 40 % of the maximum, stand out by 25 % of it
  // and lie at least 80 ms apart
  float m = 0;
  for (int i = 0; i < N; i++) {
    float s = 0; int c = 0;
    for (int j = i - 4; j <= i + 3; j++) if (j >= 0 && j < N) { s += FRM(f0 + j).eI; c++; }
    sm[i] = s / c; if (sm[i] > m) m = sm[i];
  }
  int nSub = 0, lastIdx = -1000; float lastH = 0;
  for (int i = 0; i < N; i++) {
    const float h = sm[i];
    if (h < 0.4f * m) continue;
    if ((i > 0 && sm[i - 1] > h) || (i < N - 1 && sm[i + 1] >= h)) continue;
    float mnL = h, mnR = h;
    for (int j = i - 1; j >= 0 && sm[j] <= h; j--) if (sm[j] < mnL) mnL = sm[j];
    for (int j = i + 1; j < N && sm[j] <= h; j++) if (sm[j] < mnR) mnR = sm[j];
    if (h - maxf(mnL, mnR) < 0.25f * m) continue;
    if ((i - lastIdx) * HOP < 80) { if (h > lastH) { lastIdx = i; lastH = h; } continue; }
    nSub++; lastIdx = i; lastH = h;
  }
  if (nSub < 1) nSub = 1;

  // spectral features from the filter bank, background power removed
  float eb[NBANDS], tot = 0, cen = 0;
  for (int k = 0; k < NBANDS; k++) { eb[k] = maxf(band[k] - bgBand_[k] * HOP * N, 1e-9f); tot += eb[k]; cen += BAND_FC[k] * eb[k]; }
  const float centroid = cen / tot;
  const float ratio = clampf(logf(eb[0] / (eb[1] + eb[2] + eb[3])), -5.f, 5.f);
  const float energy = maxf((sumI2 - bgI_ * HOP * N) / FS, 1e-7f);       // (mm/s)^2 . s

  e.x[F_LNPEAK] = logf(maxf(e.peakI, 1e-5f));
  e.x[F_LNENERGY] = logf(energy);
  e.x[F_DUR] = si.dur;
  e.x[F_NSUB] = (float)nSub;
  e.x[F_RISE] = si.rise;
  e.x[F_DECAY] = si.decay;
  e.x[F_BANDRATIO] = ratio;
  e.x[F_CENTROID] = centroid;
  e.x[F_RELPEAK] = 0;                                                    // filled in classify (needs the tracks)

  float *rawSig_ = e.sigRaw;
  rawSig_[0] = ss.dur; rawSig_[1] = centroid; rawSig_[2] = ratio; rawSig_[3] = ss.rise; rawSig_[4] = ss.decay;
  for (int i = 0; i < NSHAPE; i++) rawSig_[5 + i] = ss.shape[i];
  float nn = 0;
  for (int i = 0; i < NSIGV; i++) { e.sig[i] = (rawSig_[i] - wts.sigMu[i]) / wts.sigSd[i]; nn += e.sig[i] * e.sig[i]; }
  nn = sqrtf(nn) + 1e-9f;
  for (int i = 0; i < NSIGV; i++) e.sig[i] /= nn;
}

// ---------------------------------------------------------------- layer 4: score
float Detector::score(const float x[NFEAT]) const {
  float s = wts.bias;
  for (int i = 0; i < NFEAT; i++) s += wts.w[i] * (x[i] - wts.mu[i]) / wts.sd[i];
  return s;
}

// ---------------------------------------------------------------- layer 5: walker tracks
int Detector::walkers() const { int c = 0; for (int i = 0; i < MAX_TRACKS; i++) if (tr_[i].used && tr_[i].confirmed) c++; return c; }
float Detector::walkerSum() const { float s = 0; for (int i = 0; i < MAX_TRACKS; i++) if (tr_[i].used && tr_[i].confirmed) s += tr_[i].amp; return s; }
bool Detector::stepDue() const {
  for (int i = 0; i < MAX_TRACKS; i++) {
    const Track &t = tr_[i]; if (!t.used || !t.confirmed) continue;
    const float dt = (float)(n_ - t.last) / 1000.f;
    if (fabsf(dt - t.period) < cfg.timeTol * t.period) return true;
  }
  return false;
}

void Detector::expire() {
  const uint32_t now = n_;
  if (fallActive_ && !ringDone_ && now >= fallT_ + (uint32_t)cfg.ringMs) {
    // the ringing window is over: tracks that were running before the impact are assumed to have kept walking through it
    for (int i = 0; i < MAX_TRACKS; i++) {
      Track &t = tr_[i]; if (!t.used || !t.pre) continue;
      const uint32_t p = (uint32_t)(t.period * 1000.f);
      if (p > 0 && now > t.last) t.last += ((now - t.last) / p) * p;
    }
    ringDone_ = true;
  }
  for (int i = 0; i < MAX_TRACKS; i++) {
    Track &t = tr_[i]; if (!t.used) continue;
    if (fallActive_ && t.pre && !ringDone_) continue;
    const float lim = t.n >= 2 ? cfg.expirePeriods * t.period : cfg.periodMax;
    if ((float)(now - t.last) > lim * 1000.f) {
      if (t.confirmed) emit(N_TRACK_LOST, (float)i, nullptr);
      t.used = false;
    }
  }
}

// Find the track this step belongs to: the timing must fit AND the signature must match. Otherwise it may start a new track.
int Detector::assign(Event &e, bool allowNew, bool &isNew, bool &dbl, int filter) {
  isNew = dbl = false;
  const uint32_t t = e.tPk;
  int best = -1, bestK = 1; float bestCost = 1e9f, bestSim = 0;
  for (int i = 0; i < MAX_TRACKS; i++) {
    Track &tk = tr_[i]; if (!tk.used) continue;
    if ((filter == 1 && !tk.pre) || (filter == 2 && tk.pre)) continue;
    float sim = 0; for (int j = 0; j < NSIGV; j++) sim += e.sig[j] * tk.sig[j];
    const float gap = (float)(t - tk.last) / 1000.f;
    if (gap * 1000.f < (float)cfg.doubleMs && sim >= cfg.simMin) {            // heel + toe of the same footfall
      if (best < 0 || sim > bestSim) { best = i; bestSim = sim; bestCost = -1; dbl = true; }
      continue;
    }
    if (sim < cfg.simMin) continue;
    if (tk.n >= 2) {
      for (int k = 1; k <= 2; k++) {                                            // k = 2: one step was missed
        const float err = fabsf(gap - k * tk.period) / tk.period;
        if (err > cfg.timeTol) continue;
        const float cost = err + (1.f - sim) + 0.3f * (k - 1);
        if (cost < bestCost) { bestCost = cost; best = i; bestK = k; bestSim = sim; dbl = false; }
      }
    } else if (gap >= cfg.periodMin && gap <= cfg.periodMax) {
      const float cost = 0.5f + (1.f - sim);
      if (cost < bestCost) { bestCost = cost; best = i; bestK = 1; bestSim = sim; dbl = false; }
    }
  }
  if (best >= 0) {
    Track &tk = tr_[best];
    e.sim = bestSim;
    if (dbl) return best;
    const float gap = (float)(t - tk.last) / 1000.f;
    if (tk.n >= 2) { tk.period += 0.3f * (gap / bestK - tk.period); tk.steady = bestK == 1 ? tk.steady + 1 : 2; }
    else { tk.period = gap; tk.steady = 2; }
    tk.n++; tk.last = t;
    tk.amp += 0.3f * (e.peakI - tk.amp);
    float nn = 0;
    for (int j = 0; j < NSIGV; j++) { tk.sig[j] += 0.25f * (e.sig[j] - tk.sig[j]); nn += tk.sig[j] * tk.sig[j]; }
    nn = sqrtf(nn) + 1e-9f; for (int j = 0; j < NSIGV; j++) tk.sig[j] /= nn;
    if (!tk.confirmed && tk.steady >= cfg.confirmSteps) { tk.confirmed = true; emit(N_TRACK_NEW, (float)best, nullptr); }
    return best;
  }
  if (!allowNew) return -1;
  int slot = -1;
  for (int i = 0; i < MAX_TRACKS; i++) if (!tr_[i].used) { slot = i; break; }
  if (slot < 0) {                                                               // full: replace the oldest unconfirmed track
    uint32_t oldest = 0xFFFFFFFFu;
    for (int i = 0; i < MAX_TRACKS; i++) if (!tr_[i].confirmed && tr_[i].last < oldest) { oldest = tr_[i].last; slot = i; }
    if (slot < 0) { e.flags |= FL_GUESS; return -1; }                           // four confirmed walkers already
  }
  Track &tk = tr_[slot]; memset(&tk, 0, sizeof tk);
  tk.used = true; tk.n = 1; tk.steady = 1; tk.first = tk.last = t; tk.amp = e.peakI; tk.post = fallActive_;
  memcpy(tk.sig, e.sig, sizeof tk.sig);
  isNew = true;
  return slot;
}

// ---------------------------------------------------------------- layers 4 + 6: what is this event?
void Detector::classify(Event &e) {
  float maxAmp = 0;
  for (int i = 0; i < MAX_TRACKS; i++) if (tr_[i].used && tr_[i].confirmed && tr_[i].amp > maxAmp) maxAmp = tr_[i].amp;
  const float wsum = walkerSum();
  e.x[F_RELPEAK] = logf(maxf(e.peakI, 1e-5f) / (maxAmp > 0 ? maxAmp : cfg.stepRef));
  e.score = score(e.x);
  if (e.peakI >= impThAtOn_) e.flags |= FL_GATE_PEAK;                 // rule 0: impactMin; rule 1: relMin x step level (>= impactMin)
  if (e.peakI >= cfg.walkerMargin * wsum) e.flags |= FL_GATE_WALKER;
  const bool inRing = lastImpactPk_ > 0 && e.tOn - lastImpactT_ < (uint32_t)cfg.ringMs && e.peakI < 0.5f * lastImpactPk_;

  if (e.flags & FL_GATE_PEAK) {
    if (inRing) { e.cls = C_RING; return; }
    lastImpactT_ = e.tOn; lastImpactPk_ = e.peakI;
    if (!(e.flags & FL_GATE_WALKER)) { e.cls = C_IMPACT; e.flags |= FL_GUESS; return; }   // could be two walkers landing together
    if (cfg.rule == 1 ? e.hold < cfg.holdMin : e.score < cfg.scoreMin) { e.cls = C_IMPACT; return; }   // rule 1: too short for its own peak (jump, stomp, drop)
    e.cls = C_FALL;
    for (int i = 0; i < MAX_TRACKS; i++) {
      Track &t = tr_[i]; if (!t.used) continue;
      if (!fallActive_) { if (t.confirmed) { t.pre = true; t.post = false; } else t.used = false; }
      else if (t.post) t.used = false;                             // a second impact interrupts any get-up attempt
    }
    fallActive_ = true; ringDone_ = false; fallT_ = e.tOn;
    return;
  }
  if (inRing) { e.cls = C_RING; return; }
  if (e.peakS < 0.5f * cfg.stepMin) { e.cls = C_NOISE; return; }

  bool isNew, dbl;
  if (!fallActive_) {
    e.cls = C_STEP;
    e.track = (int8_t)assign(e, true, isNew, dbl);
    if (dbl) e.flags |= FL_DOUBLE;
    return;
  }
  // after a fall: bystander / movement on the floor / new step
  const bool floorLike = e.sigRaw[0] > cfg.floorDur || e.sigRaw[1] < cfg.floorCentroid;
  // first try the walkers who were already walking: a floor-like event may still be one of their steps
  int k = assign(e, false, isNew, dbl, 1);
  if (k >= 0) { e.cls = C_BYSTANDER; e.track = (int8_t)k; if (dbl) e.flags |= FL_DOUBLE; return; }
  if (floorLike) { e.cls = C_FLOOR; return; }
  k = assign(e, true, isNew, dbl, 2);
  if (k < 0) { e.cls = C_FLOOR; e.flags |= FL_GUESS; return; }
  e.cls = C_NEWSTEP; e.track = (int8_t)k; if (dbl) e.flags |= FL_DOUBLE;
  if (tr_[k].post && tr_[k].steady >= cfg.getUpSteps) { emit(N_GOTUP, (float)k, nullptr); clearFall(); }
}

void Detector::clearFall() {
  fallActive_ = false; ringDone_ = true;
  for (int i = 0; i < MAX_TRACKS; i++) { tr_[i].pre = false; tr_[i].post = false; }
}

}  // namespace rezon
