// REZON detection core. Portable C++ (no Arduino includes): the same files run on the ESP32-S3 and on the laptop.
//
//   Layer 1  signal    counts -> mm/s, offset removal, impact path 10-45 Hz, step path 18-60 Hz + hum canceller,
//                      15 ms envelopes, background followers, 4-band filter bank for the spectral features
//   Layer 2  events    the stream is cut into events (two selectable end rules, see Config::segMode)
//   Layer 3  features  feature vector x (9 numbers) and an energy-normalised signature vector (13 numbers)
//   Layer 4  score     fall score = w . z(x) + bias, plus two hard gates
//   Layer 5  tracks    up to four walkers: period, last step, mean signature, typical amplitude
//   Layer 6  after a fall-shaped event: ringing / bystander / movement on the floor / got up
//
// All work per sample is constant-time. Events are analysed from 5 ms "frames" kept in a 4 s ring.
#pragma once
#include <stdint.h>
#include <stddef.h>

namespace rezon {

constexpr int FS = 1000;            // samples per second
constexpr int HOP = 5;              // samples per frame (5 ms)
constexpr int NFRAMES = 800;        // frame history: 4 s
constexpr int NBANDS = 4;           // filter bank: 10-20, 20-30, 30-45, 45-65 Hz
constexpr int NFEAT = 9;
constexpr int NSHAPE = 8;           // envelope shape points
constexpr int NSIGV = 5 + NSHAPE;    // signature: duration, centroid, band ratio, rise, decay + shape
constexpr int MAX_TRACKS = 4;

enum Feat { F_LNPEAK, F_LNENERGY, F_DUR, F_NSUB, F_RISE, F_DECAY, F_BANDRATIO, F_CENTROID, F_RELPEAK };
extern const char *const FEAT_NAME[NFEAT];

// Event classes
enum Cls : uint8_t {
  C_NOISE,      // too small or too short to mean anything
  C_STEP,       // footstep-sized event (may belong to a walker track)
  C_IMPACT,     // passed the impact minimum but is not fall-shaped (stomp, dropped object, two people at once)
  C_FALL,       // fall-shaped: both hard gates passed and score >= threshold
  C_RING,       // inside the ringing window after an impact: ignored
  C_BYSTANDER,  // after a fall: step of a walker who was already walking before the impact. Never cancels.
  C_FLOOR,      // after a fall: movement on the floor (no rhythm or floor-contact signature). Never cancels.
  C_NEWSTEP,    // after a fall: step of a NEW track. Four steady ones = got up.
};
extern const char *const CLS_NAME[8];

// Event flags
enum : uint8_t {
  FL_GATE_PEAK = 1,     // peak >= impact minimum
  FL_GATE_WALKER = 2,   // peak clearly above what the tracked walkers produce
  FL_GUESS = 4,         // the logic is guessing here (see the note printed with the event)
  FL_DOUBLE = 8,        // second knock of the same footfall (heel + toe)
  FL_CUT = 16,          // event was cut at the maximum length, features cover only the first part
  FL_DUE = 32,          // opened with the lowered threshold because a tracked walker's step was due
};

struct Weights {
  float mu[NFEAT], sd[NFEAT];       // standardisation: z = (x - mu) / sd
  float w[NFEAT], bias;             // fall score = w . z + bias
  float sigMu[NSIGV], sigSd[NSIGV];   // centre and scale of the signature vector (step population)
};
extern const Weights DEFAULT_WEIGHTS;   // rezon_weights.h, written by tools/fit

struct Config {
  // ---- Layer 1
  float sens = 20.9f;          // geophone, mV per mm/s (SM-24 with 1 kOhm across the coil)
  int   gain = 4;              // ADC gain (1..128)
  // ---- Layer 2
  int   segMode = 1;           // 0 = variance rule (start 3x background, end 1.5x), 1 = end at 60 % of the peak
  float kOn = 3.0f;            // start: 50 ms variance > kOn x background variance ...
  float kOff = 1.5f;           // variance rule: end when it falls under kOff x background
  float stepMin = 0.020f;      // ... and step-path amplitude above this (mm/s)
  float dueDrop = 0.6f;        // threshold factor while a tracked walker's next step is due
  float endFrac = 0.6f;        // peak rule: end when both envelopes fall to this share of their peak
  float riseK = 2.0f;          // a start needs this much more power in the last 20 ms than in the quietest 20 ms just before (0 = off)
  int   refractMs = 250;       // peak rule: no new event this soon after the last peak
  int   maxStepMs = 400;       // peak rule: a small event ends this long after its peak at the latest
  int   impactWinMs = 900;     // an impact-sized event is analysed over this window from its onset
  int   maxEventMs = 2000;     // absolute cap (variance rule)
  // ---- Layer 4
  // rule 0 (absolute): impact-sized = peak >= impactMin, fall-shaped = score >= scoreMin.
  // rule 1 (normalised, distance-free): impact-sized = peak >= relMin x the step level just heard (and >= impactMin as a floor),
  //   fall-shaped = the impact envelope stays >= holdFrac of ITS OWN peak for at least holdMin. A step near the sensor is loud but
  //   no louder than the walking around it; a fall far away is quiet but much louder than that person's own steps, and it lasts.
  int   rule = 1;
  float impactMin = 0.30f;     // hard gate 1: impact-path peak, mm/s (rule 1: only an absolute floor)
  float walkerMargin = 1.5f;   // hard gate 2: peak >= margin x sum of the confirmed walkers' typical amplitudes
  float scoreMin = 0.0f;       // rule 0: fall-shaped when score >= this
  float stepRef = 0.10f;       // typical step peak when nobody is tracked (set by calibration), mm/s. Rule 1: step level when no steps were heard
  float relMin = 4.0f;         // rule 1: impact-sized when the peak is at least this many times the step level
  int   levelMs = 8000;        // rule 1: step level = second-loudest step-like event of this window ...
  int   levelGapMs = 1000;     // ... leaving out the last second (a fall often starts with a stumble or a knee: that must not lift it)
  float holdMin = 0.25f;       // rule 1: fall-shaped when the impact envelope stays >= holdFrac x its peak this long (s) ...
  float holdFrac = 0.30f;      // ... counted from 300 ms before to 600 ms after the peak
  // ---- Layer 5
  float periodMin = 0.30f, periodMax = 1.60f;   // seconds between footfalls
  float timeTol = 0.25f;       // a step fits a track within this share of its period
  float simMin = 0.20f;        // and with at least this cosine similarity of the signatures
  int   confirmSteps = 3;      // steady steps to confirm a track
  float expirePeriods = 2.5f;  // a track dies after this many periods of silence
  int   doubleMs = 250;        // two knocks closer than this on one track = one footfall
  // ---- Layer 6
  int   ringMs = 1200;         // floor ringing after an impact: ignored
  int   getUpSteps = 4;        // steady steps of a new track that mean "got up"
  float floorDur = 0.30f;      // floor contact: longer than this (s) ...
  float floorCentroid = 22.0f; // ... or centroid below this (Hz)
};

struct Event {
  uint32_t id;
  uint32_t tOn, tPk, tEnd;     // ms since start
  float peakI, peakS;          // mm/s, impact path / step path
  float x[NFEAT];              // feature vector (raw)
  float sig[NSIGV];             // signature vector, standardised and unit length
  float sigRaw[NSIGV];          // the same before standardisation: dur, centroid, band ratio, rise, decay, 8 shape points (step path)
  float score;                 // w . z + bias
  float sim;                   // cosine similarity to the assigned track (0 if none)
  float bg;                    // step-path background amplitude at the onset, mm/s
  float level;                 // step level at the onset (rule 1), mm/s
  float rel;                   // peakI / level
  float hold;                  // s the impact envelope stayed >= holdFrac x its peak (impact-sized events only, else 0)
  Cls cls;
  int8_t track;                // -1 = none
  uint8_t flags;
};

struct Track {
  bool used, confirmed;
  bool pre;                    // was confirmed and running before the current fall (bystander)
  bool post;                   // started after the current fall
  uint8_t n;                   // steps counted
  uint8_t steady;              // steps in a row that kept the rhythm
  uint32_t first, last;        // ms
  float period;                // s
  float amp;                   // typical impact-path peak, mm/s
  float sig[NSIGV];
};

// What the core tells its caller
enum NoteKind : uint8_t {
  N_EVENT,          // an event closed: ev is valid
  N_IMPACT_EARLY,   // the impact minimum was just crossed (live, before the event is analysed): value = peak so far
  N_FALL,           // fall-shaped event: ev is valid. The alarm sequence starts here.
  N_GOTUP,          // a new steady rhythm after the fall: cancels. value = track index
  N_TRACK_NEW,      // a track was confirmed. value = track index
  N_TRACK_LOST,     // a track expired. value = track index
};
struct Note { NoteKind kind; uint32_t t; float value; Event ev; };

class Detector {
 public:
  Config cfg;
  Weights wts;

  Detector();
  void reset();
  // One raw ADC sample (signed 24-bit counts). Returns the number of notes waiting (see poll).
  int push(int32_t counts);
  bool poll(Note &out);

  // After the alarm is over (button, call finished, got up): stop the post-fall classification.
  void clearFall();
  bool watching() const { return fallActive_; }
  // 0 = nothing detected yet, C_STEP / C_IMPACT / ... = class of the last event (for a status display)
  uint32_t nowMs() const { return n_; }
  float lastStep() const { return ys_; }       // step path, mm/s (hum removed)
  float lastImpact() const { return yi_; }     // impact path, mm/s
  float lastRaw() const { return v_; }         // offset removed, unfiltered, mm/s
  float background() const;                    // step-path background amplitude, mm/s
  float threshold() const { return thS_; }     // current step threshold, mm/s
  float level() const;                         // step level: second-loudest step-like event from levelMs to levelGapMs ago (stepRef if none), mm/s
  float impactThreshold() const;               // impact-path peak that makes an event impact-sized right now, mm/s
  const Track &track(int i) const { return tr_[i]; }
  int walkers() const;                         // confirmed tracks

  // Scoring helpers (also used by the tools)
  float score(const float x[NFEAT]) const;

 private:
  struct Biquad { float b0, b1, b2, a1, a2, z1, z2; };
  struct Frame { float sI2, sS2, pkI, pkS, eI, eS, b[NBANDS]; };

  // layer 1
  static Biquad mk(bool hp, float f0, float q);
  static inline float run(Biquad &k, float x) { float y = k.b0 * x + k.z1; k.z1 = k.b1 * x - k.a1 * y + k.z2; k.z2 = k.b2 * x - k.a2 * y; return y; }
  Biquad bpI_[4], bpS_[4], bank_[NBANDS][2];
  float aleW_[48], aleBuf_[128]; int alePos_;
  float ale(float x);
  bool dcInit_; float dc_, scale_; int scaleGain_; float scaleSens_;
  float v_, yi_, ys_, eI2_, eS2_;
  // frames
  Frame fr_[NFRAMES]; uint32_t nFrames_;        // nFrames_ = frames written so far; frame f lives at f % NFRAMES
  Frame acc_; int accN_;
  float vS_[10], vI_[10]; int vPos_; float vSsum_, vIsum_;   // 50 ms variance windows (10 frames)
  float bgS_, bgI_, bgBand_[NBANDS]; float thS_;
  // layer 2
  bool open_, impactSized_, earlySent_, due_;
  uint32_t fOn_, fPk_; float pkES_, pkEI_, pkYI_, bgAtOn_, levelAtOn_, impThAtOn_; int quiet_;
  static constexpr int NLEVEL = 16;            // recent step-like events: peak time (ms, 0 = empty) and impact-path peak
  uint32_t lvT_[NLEVEL]; float lvP_[NLEVEL]; int lvPos_;
  float holdOf(uint32_t fPk, uint32_t fEnd) const;
  uint32_t lastPkMs_; bool dueOn_;
  void frameDone();
  void closeEvent(uint32_t fEnd, bool cut);
  // layer 3-6
  uint32_t nextId_;
  Track tr_[MAX_TRACKS];
  bool fallActive_, ringDone_; uint32_t fallT_, lastImpactT_; float lastImpactPk_;
  void features(Event &e, uint32_t f0, uint32_t f1);
  void classify(Event &e);
  int assign(Event &e, bool allowNew, bool &isNew, bool &dbl, int filter = 0);   // filter: 0 all tracks, 1 only pre-fall, 2 only others
  void expire();
  float walkerSum() const;
  bool stepDue() const;
  // output queue
  Note q_[8]; int qHead_, qN_;
  void emit(NoteKind k, float value, const Event *e);
  uint32_t n_;
};

}  // namespace rezon
