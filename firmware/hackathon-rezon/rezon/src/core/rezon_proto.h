// REZON serial protocol: one text line per message, shared by the firmware and the laptop tools.
// Device -> host (460800 baud):
//   D,<ch1>,<ch2>                 every sample, raw signed 24-bit counts (same as the practice sketch)
//   S,<sps>,<crcErr>,<gain>,<t>,<bg>,<thS>,<walkers>,<level>,<impTh>   once per second
//   E,<id>,<tOn>,<tPk>,<durMs>,<class>,<track>,<flags>,<score>,<sim>,<peakI>,<peakS>,<bg>,<x0..x8>,<hold>,<rel>,<level>   event closed
//                                 hold = s above holdFrac of its own peak, rel = peakI / step level, level = step level (mm/s)
//   I,<t>,<peak>                  impact minimum crossed just now (live, before the event is analysed)
//   F,<t>,<id>,<score>            fall-shaped event: the alarm sequence starts
//   U,<t>,<track>                 got up (new steady rhythm): cancels
//   T,<t>,<track>,<new|lost>,<periodMs>,<amp>,<steps>
//   A,<state>,<ms>                alarm state: WATCH | GETUP | ASK | WAIT | ANNOUNCE | CALL | INCALL | DONE | OK | FAIL
//                                 <ms> = length of that state if it has one (countdown), else 0
//   M,<text>                      modem status
//   # ...                         human-readable
// Times are milliseconds since the device started sampling. Amplitudes are mm/s.
#pragma once
#include "rezon_core.h"
#include <stdio.h>

namespace rezon {

inline int fmtEvent(char *b, size_t n, const Event &e) {
  int k = snprintf(b, n, "E,%lu,%lu,%lu,%lu,%s,%d,%u,%.2f,%.2f,%.4f,%.4f,%.4f", (unsigned long)e.id, (unsigned long)e.tOn, (unsigned long)e.tPk,
                   (unsigned long)(e.tEnd - e.tOn), CLS_NAME[e.cls], (int)e.track, (unsigned)e.flags, e.score, e.sim, e.peakI, e.peakS, e.bg);
  for (int i = 0; i < NFEAT && k < (int)n; i++) k += snprintf(b + k, n - k, ",%.4f", e.x[i]);
  if (k < (int)n) k += snprintf(b + k, n - k, ",%.3f,%.2f,%.4f", e.hold, e.rel, e.level);
  return k;
}

inline int fmtNote(char *b, size_t n, const Note &o, const Detector &d) {
  switch (o.kind) {
    case N_EVENT: return fmtEvent(b, n, o.ev);
    case N_IMPACT_EARLY: return snprintf(b, n, "I,%lu,%.4f", (unsigned long)o.t, o.value);
    case N_FALL: return snprintf(b, n, "F,%lu,%lu,%.2f", (unsigned long)o.ev.tOn, (unsigned long)o.ev.id, o.ev.score);
    case N_GOTUP: return snprintf(b, n, "U,%lu,%d", (unsigned long)o.t, (int)o.value);
    case N_TRACK_NEW:
    case N_TRACK_LOST: {
      const Track &t = d.track((int)o.value);
      return snprintf(b, n, "T,%lu,%d,%s,%d,%.4f,%d", (unsigned long)o.t, (int)o.value, o.kind == N_TRACK_NEW ? "new" : "lost", (int)(t.period * 1000), t.amp, (int)t.n);
    }
  }
  return 0;
}

}  // namespace rezon
