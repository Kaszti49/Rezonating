// REZON fit: reads the event table written by "replay --events", fits the fall-score weights with regularised
// logistic regression, checks them by leaving one recording out, and writes rezon_weights.h.
//
//   fit events.tsv [--out ../rezon/src/core/rezon_weights.h] [--l2 0.3]
//
// Labels (last column): fall_stay / fall_getup / fall = 1, anything else that is labelled (drop, sit, stomp, step, other) = 0.
// Unlabelled events that did not reach the impact minimum count as 0 (steps and noise). Unlabelled impact-sized events
// are left out: we do not know what they were.
// Sign constraints (physics): peak, energy, duration, number of sub-impacts and relative peak can only RAISE the score.
// Standardisation (mu, sd) and the signature centre/scale are computed from all events, so they do not need labels.
#include "../rezon/src/core/rezon_core.h"
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <cmath>
#include <string>
#include <vector>
#include <map>
using namespace rezon;

struct Row { std::string file, label; double x[NFEAT], s[NSIGV], peak; int flags; int y; };   // y: 1 fall, 0 not, -1 unknown

static const bool NONNEG[NFEAT] = { true, true, true, true, false, false, false, false, true };

static void fitLR(const std::vector<const Row *> &rows, const double mu[], const double sd[], double l2, double w[], double &b) {
  // projected gradient descent on the class-balanced logistic loss + l2 |w|^2
  int n1 = 0, n0 = 0;
  for (auto r : rows) (r->y ? n1 : n0)++;
  const double c1 = n1 ? 0.5 / n1 : 0, c0 = n0 ? 0.5 / n0 : 0;
  for (int i = 0; i < NFEAT; i++) w[i] = 0;
  b = 0;
  const double lr = 0.5;
  for (int it = 0; it < 20000; it++) {
    double g[NFEAT] = { 0 }, gb = 0;
    for (auto r : rows) {
      double s = b;
      for (int i = 0; i < NFEAT; i++) s += w[i] * (r->x[i] - mu[i]) / sd[i];
      const double p = 1.0 / (1.0 + exp(-s)), d = (p - r->y) * (r->y ? c1 : c0);
      for (int i = 0; i < NFEAT; i++) g[i] += d * (r->x[i] - mu[i]) / sd[i];
      gb += d;
    }
    for (int i = 0; i < NFEAT; i++) {
      w[i] -= lr * (g[i] + l2 * w[i] / rows.size() * 2);
      if (NONNEG[i] && w[i] < 0) w[i] = 0;
    }
    b -= lr * gb;
  }
}

int main(int argc, char **argv) {
  std::string in, out = "../rezon/src/core/rezon_weights.h"; double l2 = 0.3;
  for (int i = 1; i < argc; i++) {
    std::string a = argv[i];
    if (a == "--out" && i + 1 < argc) out = argv[++i];
    else if (a == "--l2" && i + 1 < argc) l2 = atof(argv[++i]);
    else in = a;
  }
  if (in.empty()) { fprintf(stderr, "usage: fit events.tsv [--out weights.h] [--l2 0.3]\n"); return 2; }
  FILE *f = fopen(in.c_str(), "rb");
  if (!f) { fprintf(stderr, "cannot open %s\n", in.c_str()); return 2; }
  std::vector<Row> rows; char line[2048]; bool first = true;
  while (fgets(line, sizeof line, f)) {
    if (first) { first = false; continue; }
    std::vector<std::string> p; std::string s;
    for (char *q = line;; q++) { if (*q == '\t' || *q == '\n' || *q == '\r' || !*q) { p.push_back(s); s.clear(); if (*q != '\t') break; } else s += *q; }
    if ((int)p.size() < 12 + NFEAT + NSIGV) continue;
    Row r; r.file = p[0]; r.flags = atoi(p[6].c_str()); r.peak = atof(p[9].c_str());
    for (int i = 0; i < NFEAT; i++) r.x[i] = atof(p[12 + i].c_str());
    for (int i = 0; i < NSIGV; i++) r.s[i] = atof(p[12 + NFEAT + i].c_str());
    r.label = (int)p.size() > 12 + NFEAT + NSIGV ? p[12 + NFEAT + NSIGV] : "";
    if (!r.label.empty()) r.y = r.label.rfind("fall", 0) == 0 ? 1 : 0;
    else r.y = (r.flags & FL_GATE_PEAK) ? -1 : 0;
    rows.push_back(r);
  }
  fclose(f);
  if (rows.empty()) { fprintf(stderr, "no events in %s\n", in.c_str()); return 1; }

  // standardisation from all events; signature centre/scale from the step-sized ones
  double mu[NFEAT] = { 0 }, sd[NFEAT] = { 0 }, smu[NSIGV] = { 0 }, ssd[NSIGV] = { 0 }; int ns = 0;
  for (auto &r : rows) { for (int i = 0; i < NFEAT; i++) mu[i] += r.x[i]; if (!(r.flags & FL_GATE_PEAK)) { ns++; for (int i = 0; i < NSIGV; i++) smu[i] += r.s[i]; } }
  for (int i = 0; i < NFEAT; i++) mu[i] /= rows.size();
  for (int i = 0; i < NSIGV; i++) smu[i] /= (ns ? ns : 1);
  for (auto &r : rows) { for (int i = 0; i < NFEAT; i++) sd[i] += (r.x[i] - mu[i]) * (r.x[i] - mu[i]); if (!(r.flags & FL_GATE_PEAK)) for (int i = 0; i < NSIGV; i++) ssd[i] += (r.s[i] - smu[i]) * (r.s[i] - smu[i]); }
  for (int i = 0; i < NFEAT; i++) { sd[i] = sqrt(sd[i] / rows.size()); if (sd[i] < 1e-6) sd[i] = 1; }
  for (int i = 0; i < NSIGV; i++) { ssd[i] = sqrt(ssd[i] / (ns ? ns : 1)); if (ssd[i] < 1e-6) ssd[i] = 1; }

  std::vector<const Row *> lab; std::map<std::string, int> filesWithFalls; int n1 = 0, n0 = 0, unk = 0;
  for (auto &r : rows) { if (r.y < 0) { unk++; continue; } lab.push_back(&r); if (r.y) { n1++; filesWithFalls[r.file]++; } else n0++; }
  printf("events %zu: falls %d, not-falls %d, unlabelled impact-sized (left out) %d, recordings with falls %zu\n", rows.size(), n1, n0, unk, filesWithFalls.size());

  double w[NFEAT], b = 0; bool fitted = false;
  if (n1 >= 4 && n0 >= 10) {
    fitLR(lab, mu, sd, l2, w, b); fitted = true;
    int tp = 0, fp = 0;
    for (auto r : lab) { double s = b; for (int i = 0; i < NFEAT; i++) s += w[i] * (r->x[i] - mu[i]) / sd[i]; if (s >= 0) (r->y ? tp : fp)++; }
    printf("fit on everything: falls found %d / %d, false alarms %d / %d (score only, before the hard gates)\n", tp, n1, fp, n0);
    // leave one recording out
    if (filesWithFalls.size() >= 2) {
      int ctp = 0, cfn = 0, cfp = 0, cfpGate = 0; std::map<std::string, int> files;
      for (auto r : lab) files[r->file]++;
      for (auto &kv : files) {
        std::vector<const Row *> tr, te;
        for (auto r : lab) (r->file == kv.first ? te : tr).push_back(r);
        int t1 = 0; for (auto r : tr) t1 += r->y;
        if (t1 < 2) { printf("  leave out %-30s skipped: fewer than 2 falls left to train on\n", kv.first.c_str()); continue; }
        double ww[NFEAT], bb; fitLR(tr, mu, sd, l2, ww, bb);
        int tp2 = 0, fn2 = 0, fp2 = 0, fpg = 0;
        for (auto r : te) { double s = bb; for (int i = 0; i < NFEAT; i++) s += ww[i] * (r->x[i] - mu[i]) / sd[i];
          if (r->y) (s >= 0 ? tp2 : fn2)++; else if (s >= 0) { fp2++; if (r->flags & FL_GATE_PEAK) fpg++; } }
        printf("  leave out %-30s falls found %d / %d, false alarms %d (of which pass the impact gate: %d)\n", kv.first.c_str(), tp2, tp2 + fn2, fp2, fpg);
        ctp += tp2; cfn += fn2; cfp += fp2; cfpGate += fpg;
      }
      printf("leave-one-recording-out total: falls found %d / %d, false alarms %d (after the impact gate: %d)\n", ctp, ctp + cfn, cfp, cfpGate);
    } else printf("leave-one-recording-out: NOT POSSIBLE, falls come from fewer than 2 recordings\n");
  } else {
    printf("TOO LITTLE LABELLED DATA to fit (need at least 4 falls and 10 others): writing HAND-SET weights\n");
    const double hw[NFEAT] = { 1.0, 1.0, 0.5, 0.5, 0.0, 0.3, 0.3, 0.0, 0.5 };
    for (int i = 0; i < NFEAT; i++) w[i] = hw[i];
    b = -4.0;
  }
  printf("%-10s %9s %9s %9s\n", "feature", "mu", "sd", "weight");
  for (int i = 0; i < NFEAT; i++) printf("%-10s %9.4f %9.4f %9.4f%s\n", FEAT_NAME[i], mu[i], sd[i], w[i], NONNEG[i] ? "  (>= 0)" : "");
  printf("%-10s %29.4f\n", "bias", b);

  FILE *o = fopen(out.c_str(), "wb");
  if (!o) { fprintf(stderr, "cannot write %s\n", out.c_str()); return 1; }
  fprintf(o, "// REZON fall-score weights. Written by tools/fit from %zu events: %d falls, %d not-falls.\n", rows.size(), n1, n0);
  fprintf(o, "// %s\n", fitted ? "FITTED: regularised logistic regression, sign-constrained." : "HAND-SET weights: too little labelled data to fit.");
  fprintf(o, "// z = (x - mu) / sd, score = w . z + bias. Feature order: lnPeak lnEnergy dur nSub rise decay bandRatio centroid relPeak\n");
  fprintf(o, "#pragma once\n#include \"rezon_core.h\"\nnamespace rezon {\nconst Weights DEFAULT_WEIGHTS = {\n");
  auto arr = [&](const char *name, const double *v, int n) { fprintf(o, "  /* %-5s */ {", name); for (int i = 0; i < n; i++) fprintf(o, "%s %.5ff", i ? "," : "", v[i]); fprintf(o, " },\n"); };
  arr("mu", mu, NFEAT); arr("sd", sd, NFEAT); arr("w", w, NFEAT);
  fprintf(o, "  /* bias  */ %.5ff,\n", b);
  arr("sigMu", smu, NSIGV); arr("sigSd", ssd, NSIGV);
  fprintf(o, "};\n}\n");
  fclose(o);
  printf("wrote %s\n", out.c_str());
  return 0;
}
