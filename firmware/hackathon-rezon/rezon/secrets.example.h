// Copy this file to secrets.h (same folder) and put the real number in. secrets.h is git-ignored: the number never goes into git.
#pragma once
#define REZON_PHONE "+36XXXXXXXXX"   // the phone Rezon calls, international format
// Only if the SIM still has its PIN on (better: switch it off in a phone). It is tried once per boot: 3 wrong tries lock the SIM.
// #define REZON_SIM_PIN "1234"
