// REZON alarm sequence. Portable (no Arduino includes): the firmware feeds it time, detector notes, the button and the
// modem results; it answers with state changes and actions. Every time lives in the profile / the fields below.
//
//   WATCH --fall--> [GETUP: time to get up]* --> ASK (question plays) --> WAIT (countdown for the button)
//         --> ANNOUNCE ("calling for help" plays) --> CALL (dialling, one retry) --> INCALL --> DONE --> WATCH
//   button or got-up during GETUP / ASK / WAIT / ANNOUNCE --> OK --> WATCH        * skipped in the stage profile
//   button held 2 s while watching = panic: starts at ASK
#pragma once
#include <stdint.h>

namespace rezon {

struct Profile { const char *name; uint32_t getUpMs, askMs; };
constexpr Profile PROFILE_HOME = { "home", 5000, 10000 };    // 5 s to get up, then ask, 10 s for the button
constexpr Profile PROFILE_STAGE = { "stage", 0, 3000 };      // ask immediately, 3 s for the button

enum AState : uint8_t { A_WATCH, A_GETUP, A_ASK, A_WAIT, A_ANNOUNCE, A_CALL, A_INCALL, A_DONE, A_OK, A_FAIL };
static const char *const ASTATE_NAME[] = { "WATCH", "GETUP", "ASK", "WAIT", "ANNOUNCE", "CALL", "INCALL", "DONE", "OK", "FAIL" };
enum Action : uint8_t { ACT_NONE, ACT_PLAY_QUESTION, ACT_PLAY_CALLING, ACT_STOP_AUDIO, ACT_DIAL, ACT_HANGUP, ACT_CLEAR_FALL };

class Alarm {
 public:
  Profile prof = PROFILE_STAGE;
  uint32_t questionMs = 1600;      // length of the question clip (set from the real clip)
  uint32_t callingMs = 1500;       // length of the "calling for help" clip
  uint32_t callMaxMs = 60000;      // hang up after this long
  uint32_t dialTimeoutMs = 20000;  // no answer from the modem to ATD
  uint32_t showMs = 3000;          // how long DONE / OK / FAIL stay before WATCH
  uint32_t panicHoldMs = 2000;
  bool panicEnabled = true;

  AState state() const { return st_; }
  uint32_t stateLen() const { return len_; }                 // 0 = no fixed length
  uint32_t stateAge(uint32_t now) const { return now - t0_; }
  bool takeChange() { bool c = changed_; changed_ = false; return c; }
  Action takeAction() { if (!nAct_) return ACT_NONE; Action a = act_[0]; for (int i = 1; i < nAct_; i++) act_[i - 1] = act_[i]; nAct_--; return a; }

  void fall(uint32_t now) { if (st_ == A_WATCH) { if (prof.getUpMs) go(A_GETUP, prof.getUpMs, now); else ask(now); } }
  void gotUp(uint32_t now) { if (st_ == A_GETUP || st_ == A_ASK || st_ == A_WAIT) cancel(now); }
  void button(bool pressed, uint32_t now) {
    btn_ = pressed; if (pressed) btnT_ = now; else return;
    if (st_ == A_GETUP || st_ == A_ASK || st_ == A_WAIT || st_ == A_ANNOUNCE) cancel(now);
    else if (st_ == A_CALL || st_ == A_INCALL) { push(ACT_HANGUP); go(A_OK, showMs, now); }
  }
  void dialResult(bool ok, uint32_t now) {
    if (st_ != A_CALL) return;
    if (ok) go(A_INCALL, callMaxMs, now);
    else if (tries_ < 2) { tries_++; push(ACT_DIAL); t0_ = now; }
    else go(A_FAIL, showMs, now);
  }
  void callEnded(uint32_t now) { if (st_ == A_INCALL || st_ == A_CALL) go(A_DONE, showMs, now); }
  void test(uint32_t now) { if (st_ == A_WATCH) ask(now); }  // rehearsal: runs the sequence without a fall
  void reset(uint32_t now) { if (st_ == A_CALL || st_ == A_INCALL) push(ACT_HANGUP); push(ACT_STOP_AUDIO); push(ACT_CLEAR_FALL); go(A_WATCH, 0, now); }

  void tick(uint32_t now) {
    if (st_ == A_WATCH) {
      if (panicEnabled && btn_ && now - btnT_ >= panicHoldMs) { btnT_ = now; ask(now); }
      return;
    }
    if (!len_ || now - t0_ < len_) return;
    switch (st_) {
      case A_GETUP: ask(now); break;
      case A_ASK: go(A_WAIT, prof.askMs, now); break;
      case A_WAIT: push(ACT_PLAY_CALLING); go(A_ANNOUNCE, callingMs, now); break;
      case A_ANNOUNCE: tries_ = 1; push(ACT_DIAL); go(A_CALL, dialTimeoutMs, now); break;
      case A_CALL: dialResult(false, now); break;
      case A_INCALL: push(ACT_HANGUP); go(A_DONE, showMs, now); break;
      default: push(ACT_CLEAR_FALL); go(A_WATCH, 0, now); break;      // DONE, OK, FAIL
    }
  }

 private:
  AState st_ = A_WATCH; uint32_t t0_ = 0, len_ = 0, btnT_ = 0; bool changed_ = true, btn_ = false; int tries_ = 0;
  Action act_[6]; int nAct_ = 0;
  void push(Action a) { if (nAct_ < 6) act_[nAct_++] = a; }
  void go(AState s, uint32_t len, uint32_t now) { st_ = s; len_ = len; t0_ = now; changed_ = true; }
  void ask(uint32_t now) { push(ACT_PLAY_QUESTION); go(A_ASK, questionMs, now); }
  void cancel(uint32_t now) { push(ACT_STOP_AUDIO); push(ACT_CLEAR_FALL); go(A_OK, showMs, now); }
};

}  // namespace rezon
