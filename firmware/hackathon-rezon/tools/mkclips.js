// REZON voice clips: MP3 -> firmware/rezon/clips.h (16 kHz, 16-bit mono, silence trimmed at -46 dB, peak -1 dBFS) + WAV previews.
// Needs Node and the WebAssembly MP3 decoder, installed in any folder (nothing global):
//   mkdir dec && cd dec && npm init -y && npm install mpg123-decoder@1.0.0
// Run from the repo root:
//   node firmware/tools/mkclips.js <dec folder> firmware/rezon/clips.h <preview folder> CLIP_QUESTION=Minden_Rendben.mp3 CLIP_CALLING=Segitseget_Hivok.mp3
// Then compile and flash. CLIP_QUESTION plays at ASK, CLIP_CALLING at ANNOUNCE; the alarm timings follow the clip lengths.
const fs = require('fs'), path = require('path');
const [decDir, outH, prevDir, ...specs] = process.argv.slice(2);
const { MPEGDecoder } = require(path.join(decDir, 'node_modules', 'mpg123-decoder'));
const FS = 16000;
function resample(x, fsIn) {                       // windowed-sinc, cutoff 7.2 kHz
  const r = FS / fsIn, n = Math.floor(x.length * r), fc = 7200 / fsIn, H = 32, y = new Float32Array(n);
  for (let i = 0; i < n; i++) {
    const t = i / r, c = Math.floor(t); let s = 0, w = 0;
    for (let k = c - H + 1; k <= c + H; k++) {
      if (k < 0 || k >= x.length) continue;
      const d = t - k, sinc = d === 0 ? 2 * fc : Math.sin(2 * Math.PI * fc * d) / (Math.PI * d);
      const win = 0.42 + 0.5 * Math.cos(Math.PI * d / H) + 0.08 * Math.cos(2 * Math.PI * d / H);   // Blackman
      const g = sinc * win; s += x[k] * g; w += g;
    }
    y[i] = w ? s / w : 0;
  }
  return y;
}
function wav(file, pcm) {
  const b = Buffer.alloc(44 + pcm.length * 2);
  b.write('RIFF', 0); b.writeUInt32LE(36 + pcm.length * 2, 4); b.write('WAVEfmt ', 8); b.writeUInt32LE(16, 16); b.writeUInt16LE(1, 20); b.writeUInt16LE(1, 22);
  b.writeUInt32LE(FS, 24); b.writeUInt32LE(FS * 2, 28); b.writeUInt16LE(2, 32); b.writeUInt16LE(16, 34); b.write('data', 36); b.writeUInt32LE(pcm.length * 2, 40);
  pcm.forEach((v, i) => b.writeInt16LE(v, 44 + i * 2)); fs.writeFileSync(file, b);
}
(async () => {
  let h = '// Generated from the voice MP3s by mkclips.js (16 kHz, 16-bit mono, silence trimmed, peak -1 dBFS). Do not edit by hand.\n#pragma once\n#include <stdint.h>\n';
  for (const spec of specs) {
    const [name, file] = spec.split('=');
    const d = new MPEGDecoder(); await d.ready;
    const { channelData, sampleRate } = d.decode(new Uint8Array(fs.readFileSync(file))); d.free();
    const len = channelData[0].length, mono = new Float32Array(len);
    for (const ch of channelData) for (let i = 0; i < len; i++) mono[i] += ch[i] / channelData.length;
    let y = resample(mono, sampleRate);
    let pk = 0; for (const v of y) pk = Math.max(pk, Math.abs(v));
    const th = pk * 0.005; let a = 0, b = y.length - 1;                          // trim: below 0.5 % of the peak (-46 dB)
    while (a < b && Math.abs(y[a]) < th) a++; while (b > a && Math.abs(y[b]) < th) b--;
    a = Math.max(0, a - FS * 0.03); b = Math.min(y.length - 1, b + FS * 0.12);   // keep 30 ms before, 120 ms after
    y = y.slice(a, b + 1);
    const g = 0.891 / pk, fade = FS * 0.005;
    const pcm = Array.from(y, (v, i) => { const f = Math.min(1, i / fade, (y.length - 1 - i) / fade); return Math.round(Math.max(-1, Math.min(1, v * g * f)) * 32767); });
    wav(path.join(prevDir, name + '.wav'), pcm);
    h += `\n// ${path.basename(file)}: ${sampleRate} Hz ${channelData.length} ch in, ${(pcm.length / FS).toFixed(2)} s out\nconst int16_t ${name}[${pcm.length}] = {\n`;
    for (let i = 0; i < pcm.length; i += 20) h += '  ' + pcm.slice(i, i + 20).join(',') + ',\n';
    h += '};\n';
    console.log(`${name}: ${path.basename(file)} ${sampleRate} Hz ${channelData.length} ch, ${(len / sampleRate).toFixed(2)} s -> ${(pcm.length / FS).toFixed(2)} s, ${pcm.length * 2} bytes`);
  }
  fs.writeFileSync(outH, h); console.log('wrote', outH);
})();
