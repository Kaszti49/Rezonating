// REZON replay: feeds recordings through the detection core on the laptop and prints every event with its features,
// its track and the decision. Reads the old CSV recordings (t_ms,ch1_counts,ch2_counts[,gain,...,label]) and session
// logs saved by the training page (D, / S, / L, lines).
//
//   replay [options] file...
//     --seg 0|1          end rule: 0 = variance (3x / 1.5x background), 1 = 60 % of peak (default)
//     --set name=value   override a Config field (stepMin, impactMin, kOn, kOff, simMin, scoreMin, walkerMargin, rule, relMin, holdMin, ...)
//     --gain N           gain for files that do not say (default 4; recording 10-00-51 is 32)
//     --quiet            summary only
//     --events out.tsv   write one row per event (for labelling and tools/fit)
//     --log out.log      write a session log (D lines + E/F/U/T lines) that the pages can play back
//     --labels file.tsv  rows "file seconds label": attached to the nearest impact-sized event (+-0.7 s)
//     --mix file:fromS:toS@atS[*scale]   add that slice of another recording on top of the input, starting at atS
//     --from S --to S    only replay this part of the input
//     --profile stage|home   alarm sequence run on top (default stage); its A, lines go to the output and the log.
//                        The dial "succeeds" after 2 s; nobody presses the button.
#include "../rezon/src/core/rezon_core.h"
#include "../rezon/src/core/rezon_proto.h"
#include "../rezon/src/core/rezon_alarm.h"
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <cmath>
#include <string>
#include <vector>
#include <map>
#include <algorithm>
using namespace rezon;

struct Rec {
  std::string path, name;
  std::vector<int32_t> c;
  int gain = 0;
  std::vector<std::pair<uint32_t, std::string>> labels;
};

static std::string baseName(const std::string &p) {
  size_t a = p.find_last_of("/\\");
  std::string s = a == std::string::npos ? p : p.substr(a + 1);
  size_t d = s.find_last_of('.');
  return d == std::string::npos ? s : s.substr(0, d);
}

static std::vector<std::string> split(const char *line) {
  std::vector<std::string> p; std::string s;
  for (const char *q = line;; q++) {
    if (*q == ',' || *q == '\r' || *q == '\n' || !*q) { p.push_back(s); s.clear(); if (*q != ',') break; }
    else s += *q;
  }
  return p;
}

static bool load(const std::string &path, Rec &r, int defGain) {
  FILE *f = fopen(path.c_str(), "rb");
  if (!f) { fprintf(stderr, "cannot open %s\n", path.c_str()); return false; }
  r.path = path; r.name = baseName(path);
  char line[512]; int gainCol = -1, labelCol = -1; bool csv = false, first = true;
  while (fgets(line, sizeof line, f)) {
    if (first) {
      first = false;
      if (!strncmp(line, "t_ms", 4)) {
        csv = true;
        std::vector<std::string> h = split(line);
        for (size_t i = 0; i < h.size(); i++) { if (h[i] == "gain") gainCol = (int)i; if (h[i] == "label") labelCol = (int)i; }
        continue;
      }
    }
    if (csv) {
      std::vector<std::string> p = split(line);
      if (p.size() < 2) continue;
      r.c.push_back((int32_t)atol(p[1].c_str()));
      if (gainCol >= 0 && (int)p.size() > gainCol && !r.gain) r.gain = atoi(p[gainCol].c_str());
      if (labelCol >= 0 && (int)p.size() > labelCol && !p[labelCol].empty()) r.labels.push_back({ (uint32_t)r.c.size() - 1, p[labelCol] });
    } else if (line[0] == 'D' && line[1] == ',') {
      r.c.push_back((int32_t)atol(line + 2));
    } else if (line[0] == 'S' && line[1] == ',') {
      int a, b, g;
      if (sscanf(line + 2, "%d,%d,%d", &a, &b, &g) == 3 && !r.gain) r.gain = g;
    } else if (line[0] == 'L' && line[1] == ',') {
      std::string s(line + 2);
      while (!s.empty() && (s.back() == '\n' || s.back() == '\r')) s.pop_back();
      r.labels.push_back({ (uint32_t)r.c.size(), s });
    }
  }
  fclose(f);
  if (!r.gain) r.gain = r.name.find("10-00-51") != std::string::npos ? 32 : defGain;
  return !r.c.empty();
}

static bool setCfg(Config &c, const std::string &kv) {
  size_t eq = kv.find('=');
  if (eq == std::string::npos) return false;
  std::string k = kv.substr(0, eq);
  double v = atof(kv.c_str() + eq + 1);
#define F(n) if (k == #n) { c.n = (decltype(c.n))v; return true; }
  F(sens) F(gain) F(segMode) F(kOn) F(kOff) F(stepMin) F(dueDrop) F(endFrac) F(riseK) F(refractMs) F(maxStepMs) F(impactWinMs) F(maxEventMs)
  F(impactMin) F(walkerMargin) F(scoreMin) F(stepRef) F(periodMin) F(periodMax) F(timeTol) F(simMin) F(confirmSteps) F(expirePeriods)
  F(doubleMs) F(ringMs) F(getUpSteps) F(floorDur) F(floorCentroid) F(rule) F(relMin) F(levelMs) F(levelGapMs) F(holdMin) F(holdFrac)
#undef F
  return false;
}

int main(int argc, char **argv) {
  Config cfg; bool quiet = false; int defGain = 4;
  std::string evPath, logPath, labPath, profile = "stage"; std::vector<std::string> files, mixes; double fromS = 0, toS = 1e9;
  for (int i = 1; i < argc; i++) {
    std::string a = argv[i];
    auto next = [&]() { return std::string(i + 1 < argc ? argv[++i] : ""); };
    if (a == "--seg") cfg.segMode = atoi(next().c_str());
    else if (a == "--set") { std::string kv = next(); if (!setCfg(cfg, kv)) { fprintf(stderr, "unknown setting %s\n", kv.c_str()); return 2; } }
    else if (a == "--gain") defGain = atoi(next().c_str());
    else if (a == "--quiet") quiet = true;
    else if (a == "--events") evPath = next();
    else if (a == "--log") logPath = next();
    else if (a == "--labels") labPath = next();
    else if (a == "--mix") mixes.push_back(next());
    else if (a == "--profile") profile = next();
    else if (a == "--from") fromS = atof(next().c_str());
    else if (a == "--to") toS = atof(next().c_str());
    else files.push_back(a);
  }
  if (files.empty()) {
    fprintf(stderr, "usage: replay [--seg 0|1] [--set k=v] [--quiet] [--events out.tsv] [--log out.log] [--labels l.tsv] [--mix f:from:to@at] file...\n");
    return 2;
  }

  std::multimap<std::string, std::pair<double, std::string>> ext;      // labels from the side file
  if (!labPath.empty()) {
    FILE *f = fopen(labPath.c_str(), "rb"); char l[256], n[128], lb[64]; double t;
    if (f) { while (fgets(l, sizeof l, f)) if (l[0] != '#' && sscanf(l, "%127s %lf %63s", n, &t, lb) == 3) ext.insert({ n, { t, lb } }); fclose(f); }
    else fprintf(stderr, "cannot open labels %s\n", labPath.c_str());
  }

  FILE *ev = nullptr;
  if (!evPath.empty()) {
    ev = fopen(evPath.c_str(), "wb");
    fprintf(ev, "file\tid\tt_s\tdur_ms\tclass\ttrack\tflags\tscore\tsim\tpeakI\tpeakS\tbg");
    for (int i = 0; i < NFEAT; i++) fprintf(ev, "\t%s", FEAT_NAME[i]);
    for (int i = 0; i < NSIGV; i++) fprintf(ev, "\ts%d", i);
    fprintf(ev, "\tlabel\thold\trel\tlevel\n");
  }
  FILE *lg = logPath.empty() ? nullptr : fopen(logPath.c_str(), "wb");

  static Detector det;
  for (const std::string &path : files) {
    Rec r;
    if (!load(path, r, defGain)) continue;
    size_t a0 = (size_t)std::min<double>(fromS * FS, (double)r.c.size()), a1 = (size_t)std::min<double>(toS * FS, (double)r.c.size());
    if (a0 > 0 || a1 < r.c.size()) r.c = std::vector<int32_t>(r.c.begin() + a0, r.c.begin() + a1);
    for (const std::string &m : mixes) {                                // file:from:to@at[*scale]
      size_t at = m.rfind('@'), c2 = at == std::string::npos ? at : m.rfind(':', at), c1 = c2 == std::string::npos || c2 == 0 ? std::string::npos : m.rfind(':', c2 - 1);
      if (c1 == std::string::npos) { fprintf(stderr, "bad --mix %s\n", m.c_str()); return 2; }
      const std::string fn = m.substr(0, c1);
      const double f0 = atof(m.c_str() + c1 + 1), f1 = atof(m.c_str() + c2 + 1), atS = atof(m.c_str() + at + 1);
      size_t star = m.find('*', at); const double sc = star == std::string::npos ? 1.0 : atof(m.c_str() + star + 1);
      Rec b;
      if (!load(fn, b, defGain)) return 2;
      size_t i0 = (size_t)(f0 * FS), i1 = std::min((size_t)(f1 * FS), b.c.size());
      if (i0 >= i1) continue;
      std::vector<int32_t> seg(b.c.begin() + i0, b.c.begin() + i1), srt = seg;
      std::nth_element(srt.begin(), srt.begin() + srt.size() / 2, srt.end());
      const double med = srt[srt.size() / 2], g = sc * (double)r.gain / b.gain; const double fade = 100;
      for (size_t i = 0; i < seg.size(); i++) {
        size_t j = (size_t)(atS * FS) + i;
        if (j >= r.c.size()) break;
        double w = std::min(1.0, std::min((double)i, (double)(seg.size() - 1 - i)) / fade);
        r.c[j] += (int32_t)lround((seg[i] - med) * g * w);
      }
    }
    det.cfg = cfg; det.cfg.gain = r.gain; det.reset();
    if (!quiet) printf("== %s  (%.1f s, gain %d, end rule %s)\n", r.name.c_str(), r.c.size() / 1000.0, r.gain, cfg.segMode ? "60%-of-peak" : "variance");
    if (lg) fprintf(lg, "# replay of %s\nS,1000,0,%d\n", r.name.c_str(), r.gain);
    int cnt[8] = { 0 }, falls = 0, gotups = 0, tracks = 0; std::vector<Event> evs;
    char buf[400]; Note o;
    Alarm al; al.prof = profile == "home" ? PROFILE_HOME : PROFILE_STAGE; al.takeChange();
    uint32_t dialAt = 0; int calls = 0, cancelled = 0;
    for (size_t i = 0; i < r.c.size(); i++) {
      if (lg) fprintf(lg, "D,%d,0\n", (int)r.c[i]);
      const uint32_t now = (uint32_t)i;
      al.tick(now);
      for (Action a; (a = al.takeAction()) != ACT_NONE;) {
        if (a == ACT_DIAL) { dialAt = now + 2000; calls++; }
        if (a == ACT_CLEAR_FALL) det.clearFall();
      }
      if (dialAt && now >= dialAt) { dialAt = 0; al.dialResult(true, now); }
      if (al.takeChange()) {
        if (al.state() == A_OK) cancelled++;
        if (lg) fprintf(lg, "A,%s,%lu\n", ASTATE_NAME[al.state()], (unsigned long)al.stateLen());
        if (!quiet) printf("%8.3f  >> A,%s,%lu\n", now / 1000.0, ASTATE_NAME[al.state()], (unsigned long)al.stateLen());
      }
      if (!det.push(r.c[i])) continue;
      while (det.poll(o)) {
        fmtNote(buf, sizeof buf, o, det);
        if (lg) fprintf(lg, "%s\n", buf);
        if (o.kind == N_EVENT) {
          const Event &e = o.ev;
          cnt[e.cls]++; evs.push_back(e);
          if (quiet) continue;
          printf("%8.3f  %-9s trk %2d  pk %7.3f  step %6.3f  lvl %6.3f  x%5.1f  hold %3.0f ms  score %6.2f  sim %5.2f  dur %4lu ms |", e.tOn / 1000.0, CLS_NAME[e.cls], (int)e.track, e.peakI, e.peakS, e.level, e.rel, e.hold * 1000, e.score, e.sim, (unsigned long)(e.tEnd - e.tOn));
          printf(" E %5.1f d %.3f n %d r %.3f dc %.3f br %5.2f fc %4.1f rel %5.2f%s%s%s%s\n", e.x[F_LNENERGY], e.x[F_DUR], (int)e.x[F_NSUB], e.x[F_RISE], e.x[F_DECAY], e.x[F_BANDRATIO], e.x[F_CENTROID], e.x[F_RELPEAK],
                 (e.flags & FL_GUESS) ? " GUESS" : "", (e.flags & FL_DOUBLE) ? " double" : "", (e.flags & FL_CUT) ? " cut" : "", (e.flags & FL_DUE) ? " due" : "");
        } else {
          if (o.kind == N_FALL) { falls++; al.fall(now); }
          if (o.kind == N_GOTUP) { gotups++; al.gotUp(now); }
          if (o.kind == N_TRACK_NEW) tracks++;
          if (!quiet && o.kind != N_IMPACT_EARLY) printf("%8.3f  >> %s\n", o.t / 1000.0, buf);
        }
      }
    }
    // labels: from the recording itself and from the side file, attached to the nearest impact-sized event
    std::vector<std::string> lab(evs.size());
    auto attach = [&](double t, const std::string &l) {
      int best = -1; double bd = 0.7;
      for (size_t k = 0; k < evs.size(); k++) {
        if (!(evs[k].flags & FL_GATE_PEAK)) continue;
        double d = fabs(evs[k].tOn / 1000.0 - t);
        if (d < bd) { bd = d; best = (int)k; }
      }
      if (best >= 0) lab[best] = l;
      else fprintf(stderr, "label %s at %.1f s in %s: no impact-sized event nearby\n", l.c_str(), t, r.name.c_str());
    };
    for (auto &l : r.labels) attach(l.first / 1000.0, l.second);
    auto rg = ext.equal_range(r.name);
    for (auto it = rg.first; it != rg.second; ++it) attach(it->second.first, it->second.second);
    if (ev) for (size_t k = 0; k < evs.size(); k++) {
      const Event &e = evs[k];
      fprintf(ev, "%s\t%lu\t%.3f\t%lu\t%s\t%d\t%u\t%.3f\t%.3f\t%.4f\t%.4f\t%.4f", r.name.c_str(), (unsigned long)e.id, e.tOn / 1000.0, (unsigned long)(e.tEnd - e.tOn), CLS_NAME[e.cls], (int)e.track, (unsigned)e.flags, e.score, e.sim, e.peakI, e.peakS, e.bg);
      for (int i = 0; i < NFEAT; i++) fprintf(ev, "\t%.5f", e.x[i]);
      for (int i = 0; i < NSIGV; i++) fprintf(ev, "\t%.5f", e.sigRaw[i]);
      fprintf(ev, "\t%s\t%.3f\t%.3f\t%.4f\n", lab[k].c_str(), e.hold, e.rel, e.level);
    }
    int onTrack = 0;
    for (auto &e : evs) if ((e.cls == C_STEP || e.cls == C_BYSTANDER || e.cls == C_NEWSTEP) && e.track >= 0) onTrack++;
    printf("-- %-26s events %3zu | fall-shaped %d  impact %d  step %d  ring %d  bystander %d  floor %d  newstep %d  noise %d | steps on a track %d  tracks confirmed %d  got-up %d | alarm: calls %d  cancelled %d\n",
           r.name.c_str(), evs.size(), falls, cnt[C_IMPACT], cnt[C_STEP], cnt[C_RING], cnt[C_BYSTANDER], cnt[C_FLOOR], cnt[C_NEWSTEP], cnt[C_NOISE], onTrack, tracks, gotups, calls, cancelled);
  }
  if (ev) fclose(ev);
  if (lg) fclose(lg);
  return 0;
}
