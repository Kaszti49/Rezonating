"""Single source for the Rezon parts list.
Writes  parts_list.html (print to PDF with Edge, see build.cmd)  and  ../Hackathon_shopping_list_SM24.csv.
python parts.py <out_dir>"""
import html, os, sys

OUT = sys.argv[1] if len(sys.argv) > 1 else 'out'
DATE = '2026-11-13'
esc = html.escape

# (qty, name, code, stock row, source, purpose EN, purpose HU, backup?)
# source: 'Hackathon' (Hestore stock list, row = line in Hackathon_5_alkatreszek(Hestore).csv), 'Ours', 'Buy'
SECTIONS = [
    ('Sensing & processing', [
        (1, 'SM-24 geophone (SparkFun SEN-11744)', '', '', 'Ours',
         'Floor vibration sensor, 28.8 V/(m/s), 10–240 Hz', 'Padló rezgésérzékelő, 28.8 V/(m/s), 10–240 Hz', False),
        (1, 'MikroE ADC 15 Click (ADS131M02, 24-bit, 2 ch)', 'MIKROE-4890', '', 'Ours',
         'Geophone straight into the ADC at gain 32 (±37.5 mV full scale); firmware already brought up',
         'Geofon → ADC, gain 32 (±37.5 mV), a firmware már fut rajta', False),
        (1, 'ESP32 S3 fejlesztői modul, 16MB Flash, 8MB PSRAM, WiFi, BT5, USB-C', 'ESP32-S3-WROOM-1-N16R8-M', '179', 'Hackathon',
         'Main controller; exact target of our firmware (PSRAM for buffers and the model). Also drives the SIM868 board',
         'Mikrokontroller, a firmware célhardvere (esp32s3, PSRAM); ez vezérli a SIM868 panelt is', False),
        (1, '16 bites analog-digital konverter modul, I2C', 'ADS1115-M', '11', 'Hackathon',
         'Only if the Click fails: ±0.256 V range, max 860 SPS; enough for fall impacts',
         'Csak ha a Click nem működik: PGA ±0.256 V, max 860 SPS', True),
    ]),
    ('Alert: call, voice, light, button', [
        (1, 'Waveshare Pico-SIM868-GSM/GPRS/GNSS board (SIM868: 2G GSM/GPRS + GNSS + BT)', '', '', 'Ours',
         'Calls our phone when a fall is confirmed and nobody presses “I’m OK”. Used as a modem only: Pico H removed, the ESP32-S3 drives it over UART',
         'Hívja a telefonunkat, ha esés van és senki nem nyomja meg a „Jól vagyok” gombot. Csak modemként: a Pico H lekerül róla, az ESP32-S3 vezérli UART-on', False),
        (1, 'GSM antenna with u.FL (IPEX) plug, 850/900/1800/1900 MHz', '', '', 'Ours',
         'Goes on the board’s “GSM” socket; mandatory. It should be in the Waveshare box (none is fitted in our photo): buy one if it is missing',
         'A panel „GSM” u.FL aljzatára, kötelező. A Waveshare dobozában kell lennie (a fotón nincs felrakva); ha hiányzik, venni kell', False),
        (1, 'PH2.0 (JST-PH 2.0 mm) 2-pin plug with ~10 cm leads', '', '', 'Buy',
         '4.0 V from the step-down into the SIM868 board’s battery socket. Not in the hackathon stock; check polarity against the box’s Li-po plug',
         '4.0 V a step-downról → a SIM868 panel akku aljzatába. Nincs a hackathon listán; a polaritást a dobozban lévő Li-po dugójához kell igazítani', False),
        (1, 'SIM card from one of our phones (PIN disabled), nano', '', '', 'Ours',
         'Network access for the call; must work on 2G. The SIM868 board takes a nano SIM directly, no adapter',
         'Hálózat a híváshoz, 2G kell. A SIM868 panel nano SIM-et fogad, adapter nem kell', False),
        (1, 'PCM5102A alapú DAC audió dekóder I2S modul', '', '249', 'Hackathon',
         'Audio out for “Mari néni, jól van?”; the S3 has no built-in DAC', 'Hang kimenet (az S3-nak nincs DAC-ja): „Mari néni, jól van?”', False),
        (1, 'ZK-502M Bluetooth / AUX amplifier board (TPA3116D2, 2 × 50 W, 5–24 V)', 'ZK-502M', '', 'Ours',
         'Speaker amplifier instead of the PAM8403, fed from the 5 V rail; volume knob low (1 W speaker)', 'Erősítő a PAM8403 helyett, 5 V-ról; hangerő alacsonyan (1 W-os hangszóró)', False),
        (1, '3.5 mm male–male AUX cable', '', '', 'Ours',
         'PCM5102A line-out jack → ZK-502M AUX input', 'PCM5102A vonalkimenet → ZK-502M AUX bemenet', False),
        (1, 'Hangszóró, kicsi 1W 8ohm', '', '262', 'Hackathon', 'Speaker', 'Hangszóró', False),
        (1, 'WS2812B RGB vezérelhető LED szalag, 1 m, 60 LED/m', 'WS2812B-LS-60-IP20-BK', '68', 'Hackathon',
         'Cut one pixel: green / amber / red status LED', '1 pixelt vágunk le: zöld / sárga / piros státusz LED', False),
        (1, '1N4001 dióda', '', '364', 'Hackathon',
         'Drops the LED supply to ~4.3 V so it reliably reads the 3.3 V data line', 'WS2812B VDD 5 V → ~4.3 V, hogy a 3.3 V-os adatjelet biztosan lássa', False),
        (2, 'TACT mikrokapcsoló, SPST-NO, THT, 6x6mm, 5mm', 'TACT-65R-F', '51', 'Hackathon',
         '“I’m OK” / cancel-alarm button (+1 spare)', '„Jól vagyok” / riasztás törlés gomb (+1 tartalék)', False),
    ]),
    ('Power', [
        (1, 'Power bank with USB-A out, USB-C in (5 V)', '', '', 'Ours',
         'The only power source: 5 V for everything, charged over its USB-C. Sits outside the case; must not auto-off at low load (test it, use its always-on mode if it has one). A 5 W one gives ~1 A in total',
         'Az egyetlen táp: 5 V mindennek, USB-C-n tölthető. A dobozon kívül van; kis terhelésnél nem kapcsolhat le (tesztelni, ha van, always-on mód). Egy 5 W-os kb. 1 A-t ad összesen', False),
        (1, 'USB-A cable (any; far end cut off)', '', '', 'Ours',
         'Power bank → inside the case through a grommet: red = 5 V, black = GND', 'Power bank → a dobozba egy gumialátéten át: piros = 5 V, fekete = GND', False),
        (1, 'Kapcsolóüzemű DC-DC konverter (STP28UD-3A, step-up/step-down, 1.25–26 V, 1 A without heatsink)', 'STP28UD-3A', '291', 'Hackathon',
         '5 V → 4.0 V for the SIM868 (it must never get 5 V); set with its trimmer before connecting',
         '5 V → 4.0 V a SIM868-nak (5 V-ot soha nem kaphat); a trimmerrel beállítva, mielőtt rákötjük', False),
        (1, 'Világítás billenőkapcsoló, 12V, SPST, OFF-ON', 'AK-01', '46', 'Hackathon',
         'Main power switch in the power bank’s 5 V line', 'Főkapcsoló a power bank 5 V-os vezetékében', False),
        (1, 'Fémréteg ellenállás készlet, 500 db, 50 érték, 0.5W, 1%', 'RESISTOR-KIT-500P', '165', 'Hackathon',
         '1 kΩ across the geophone coil · 2 × 100 kΩ VBAT divider · 10 kΩ button pull-up (no SIM divider any more)',
         '1 kΩ sönt a geofon tekercsére, 2×100 kΩ akkufeszültség-osztó, 10 kΩ felhúzó a gombhoz (SIM osztó már nem kell)', False),
        (1, 'Elektrolit kondenzátor készlet, 0.1uF–1000uF, 500 db', 'ELCOPACK-500', '166', 'Hackathon',
         '1000 µF at the SIM868 power take-off · 470–1000 µF on the 5 V rail', '1000 µF a SIM868 tápleágazásánál, 470–1000 µF az 5 V sínre', False),
        (1, 'Kerámia kondenzátor készlet, 24 féle, 960 db', 'CER-CAP-PACK', '167', 'Hackathon',
         '100 nF decoupling at each module’s supply', '100 nF hidegítők a modulok tápjára', False),
    ]),
    ('Wiring & assembly', [
        (1, '9x15 cm, kétoldalas furatgalvánozott, univerzális nyák, FR4', 'DPCB-915', '101', 'Hackathon',
         'Base board (cut to fit the case); the SIM868 board stands off-board at the back wall', 'Alaplap (méretre vágva); a SIM868 panel külön áll a doboz hátsó falánál', False),
        (2, 'Tüskesor aljzat, egyenes, 40 pin', 'ZL262-40SG', '131', 'Hackathon',
         'Sockets so the ESP32-S3 and Click stay swappable', 'ESP32-S3 és Click cserélhetően a nyákon', False),
        (1, 'Tüskesor, egyenes, tördelhető, 40 pin', 'ZL201-40G (WWS40G)', '130', 'Hackathon',
         'Pin headers for modules that lack them, and H2 (5 pins) for the SIM868 jumpers', 'Tüskék a modulokhoz, ahol nincs, és H2 (5 tüske) a SIM868 jumperekhez', False),
        (1, 'Szalagkábel csatlakozóval, 10cm, 40p, female-female (jumper)', 'RC-40-10/FF', '42', 'Hackathon',
         'Click mikroBUS → ESP32-S3 (SCK, SDO, SDI, CS1, CS2, INT, RST, 3V3, GND), lid harness', 'Click mikroBUS → ESP32-S3 (SCK, SDO, SDI, CS1, CS2, INT, RST, 3V3, GND), fedél kábelköteg', False),
        (1, 'Szalagkábel csatlakozóval, 10cm, 40p, male-female (jumper)', 'RC-40-10/MF', '39', 'Hackathon',
         '5 jumpers H2 → SIM868 board: the male end goes straight into the board’s Pico sockets', '5 jumper H2 → SIM868 panel: a male vég közvetlenül a panel Pico aljzatába megy', False),
        (1, 'kábel 6x0,22', '', '359', 'Hackathon', 'Geophone lead (one twisted pair), about 1 m; board links', 'Geofon vezeték (1 sodrott pár), ~1 m; átkötések', False),
        (1, 'Vezeték, H05V-K, sodrat, Cu, 1 x 0.5mm², piros', '', '353', 'Hackathon',
         '5 V / step-down / SIM868 battery lead', '5 V / step-down / SIM868 akku vezeték', False),
        (1, 'Vezeték, H05V-K, sodrat, Cu, 1 x 0.5mm², fekete', '', '352', 'Hackathon', 'GND', 'GND', False),
        (1, 'Egymagos vörösréz huzal 20 AWG, 15 m', '', '349', 'Hackathon', 'Rails and buses on the perfboard', 'Sínek a nyákon', False),
        (1, 'Zsugorcső készlet (2:1), 530 db', 'HST-SET530', '157', 'Hackathon', 'Insulation', 'Szigetelés', False),
        (1, 'USB 2.0 kábel, USB A – USB C, 3A, 1.5m', 'CTHBG', '138', 'Hackathon', 'Flashing and serial monitor', 'Flashelés, soros monitor', False),
        (1, 'M3 távtartó készlet', '', '205', 'Hackathon', 'Mount the board in the printed case', 'Nyák rögzítése a nyomtatott dobozba', False),
        (1, 'Csavar készlet M2–M6', '', '302', 'Hackathon', 'Fixings', 'Rögzítés', False),
        (1, 'Kábelkötegelő (100 db), fekete, 2.5 × 100 mm', 'CV 100/2,5/B', '64', 'Hackathon', 'Cable management and strain relief', 'Kábelrendezés, tehermentesítés', False),
    ]),
]

# tools and optional extras: only in the CSV (the PDF leaves them out on purpose)
CSV_EXTRA = [
    '1;Ólommentes forrasztóón, 0.7mm/0.1kg, Sn99.3Cu0.7;SN99C-0.7/0.1;25;Hackathon;Forrasztás',
    '1;Folyasztószer toll, Mini-Fluxer, no-clean, X32-10i, 10ml;MF-X3210I;31;Hackathon;Forrasztás',
    '1;Ónszívó szalag, 1 mm x 1,5 m;ZD-180-1;30;Hackathon;Javítás',
    '1;Segédkéz;;285;Hackathon;Szerszám',
    '1;Blankoló;;281;Hackathon;Szerszám',
    '1;Fogó készlet;;284;Hackathon;Szerszám',
    '1;Csavarhúzó készlet;;282;Hackathon;Click sorkapcsok (kis lapos)',
    '1;Multiméter;;;SAJÁT;Nincs a listán – step-down 4.0 V beállítása, USB kábel erek, folytonosság',
    '1;Micro SD kártya;;305;Hackathon (opcionális);Csak ha rezgésadatot akarunk rögzíteni tanításhoz',
    '1;SD kártya olvasó SPI modul;;252;Hackathon (opcionális);Csak ha rezgésadatot akarunk rögzíteni tanításhoz',
    '1;10k Potenciométer;;209;Hackathon (opcionális);Hangerő a DAC és az erősítő között, ha szoftverből nem elég',
    '1;Piezo hangjelző házban, 80dB @ 5V, gerjesztő áramkör nélkül, d=12.5mm, 4kHz;SFN-1207PA6.5;34;Hackathon (opcionális);Tartalék riasztó hang, ha a hangszóró-lánc nem áll össze',
]

css = """
@page { size: A4; margin: 10mm 11mm 10mm 11mm; }
* { box-sizing: border-box; }
body { margin: 0; font-family: "IBM Plex Sans", "Segoe UI", Arial, sans-serif; color: #2a2c2e; font-size: 8.1pt; line-height: 1.3; }
.head { display: flex; justify-content: space-between; align-items: flex-end; border-bottom: 2px solid #5f8f8b; padding-bottom: 6px; }
h1 { font-size: 19pt; margin: 0 0 2px; } h1 b { color: #2f8f8b; letter-spacing: .5px; }
.sub { color: #6f7377; font-size: 9pt; max-width: 125mm; } .date { text-align: right; color: #6f7377; font-size: 8pt; } .date b { color: #2a2c2e; font-size: 9pt; }
.grid2 { display: grid; grid-template-columns: 1.15fr 1fr; gap: 9px; margin-top: 9px; }
.box { border: 1px solid #ddd8cf; border-radius: 6px; padding: 7px 10px; }
.box h3, .setup h3 { margin: 0 0 5px; font: 700 8pt "IBM Plex Sans", Arial; letter-spacing: .8px; text-transform: uppercase; color: #2f8f8b; }
.ours { background: #fdf3e1; border-color: #efd7a6; } .ours h3 { color: #a8701c; }
.ours ul, .setup ul { margin: 0; padding-left: 14px; } .ours li, .setup li { margin: 1.5px 0; }
.chain { margin: 3px 0; color: #55595d; } .chain span { display: inline-block; border: 1px solid #b9d5d2; background: #eef6f5; color: #2a2c2e; border-radius: 4px; padding: 1px 6px; margin: 1px 0; }
.setup { margin-top: 9px; background: #e9f3f2; border: 1px solid #bcd9d6; border-radius: 6px; padding: 7px 10px; }
.setup .cols { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
h2 { font-size: 10.5pt; margin: 9px 0 3px; padding-left: 7px; border-left: 3px solid #2f8f8b; }
table { width: 100%; border-collapse: collapse; }
th { text-align: left; font: 600 6.8pt "IBM Plex Sans", Arial; letter-spacing: .5px; text-transform: uppercase; color: #7b7f83; background: #f4f2ee; padding: 3px 4px; }
td { padding: 2.6px 4px; border-bottom: 1px solid #e6e1d8; vertical-align: top; }
tr { page-break-inside: avoid; }
tr.ours td { background: #fdf6e8; } tr.buy td { background: #fbeeea; } tr.backup td { color: #6f7377; }
td.cb { width: 14px; } .cbx { display: inline-block; width: 9px; height: 9px; border: 1.1px solid #8c959f; border-radius: 2px; margin-top: 2px; }
td.q { width: 28px; font-weight: 700; text-align: center; } td.row { width: 34px; text-align: center; color: #55595d; } td.src { width: 66px; } td.p { width: 39%; }
.code { display: block; font: 7pt "IBM Plex Mono", monospace; color: #7b7f83; margin-top: 1px; }
.badge { display: inline-block; font: 700 6.8pt "IBM Plex Sans", Arial; border-radius: 3px; padding: 0 5px; }
.b-Hackathon { background: #e3e6e8; color: #4b5156; } .b-Ours { background: #f6e3bf; color: #95621a; border: 1px solid #e6c88f; } .b-Buy { background: #f3d2ca; color: #8e3b2c; border: 1px solid #e4b0a4; }
.bk { display: inline-block; font: 700 6.4pt "IBM Plex Sans", Arial; background: #e3e6e8; color: #55595d; border-radius: 3px; padding: 0 4px; margin-top: 2px; }
.foot { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; margin-top: 9px; color: #6f7377; font-size: 7.6pt; }
"""

def row_html(r):
    q, name, code, row, src, pen, _, backup = r
    cls = 'ours' if src == 'Ours' else 'buy' if src == 'Buy' else ('backup' if backup else '')
    codeh = f'<span class="code">{esc(code)}</span>' if code else ''
    bk = '<br><span class="bk">BACKUP</span>' if backup else ''
    return (f'<tr class="{cls}"><td class="cb"><span class="cbx"></span></td><td class="q">{q}</td><td>{esc(name)}{bk}{codeh}</td>'
            f'<td class="row">{row or "–"}</td><td class="src"><span class="badge b-{src}">{src}</span></td><td class="p">{esc(pen)}</td></tr>')

o = [f'<!doctype html><html><head><meta charset="utf-8"><title>Rezon Parts List</title>'
     '<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono&family=IBM+Plex+Sans:wght@400;600;700&display=swap" rel="stylesheet">'
     f'<style>{css}</style></head><body>']
o.append(f'<div class="head"><div><h1><b>REZON</b> fall detector · parts list</h1><div class="sub">Hackathon build with the SM-24 geophone and a SIM868 call alert · casing 3D-printed on site · no breadboard</div></div>'
         f'<div class="date"><b>{DATE}</b><br>Row = line in the Hestore stock CSV</div></div>')
o.append('<div class="grid2"><div class="box"><h3>Signal chain</h3>'
         '<div class="chain"><span>SM-24 geophone</span> → <span>ADC 15 Click</span> → SPI → <span>ESP32-S3</span></div>'
         '<div class="chain">ESP32-S3 → I²S → <span>PCM5102A</span> → AUX → <span>ZK-502M</span> → <span>Speaker</span></div>'
         '<div class="chain">ESP32-S3 → UART → <span>SIM868 (Waveshare)</span> → GSM call → <span>our phone</span></div>'
         '<div style="color:#6f7377;margin-top:3px">Plus a WS2812B status LED (green / amber / red) and an “I’m OK” button. A power bank (outside the case) is the only source: 5 V for everything, and a step-down makes 4.0 V for the SIM868.</div></div>'
         '<div class="box ours"><h3>Ours / to buy (not in hackathon stock)</h3><ul>'
         '<li><b>SM-24 geophone</b> (here)</li><li><b>MikroE ADC 15 Click</b> (ADS131M02, already running on the bench)</li>'
         '<li><b>Waveshare Pico-SIM868 board</b> (here) + its <b>GSM antenna</b>: check the box, buy one if missing</li>'
         '<li><b>Nano SIM</b> from one of our phones, PIN off</li><li><b>Power bank</b> (USB-A out) + a USB-A cable to cut</li>'
         '<li><b>To buy:</b> PH2.0 2-pin plug with leads (battery lead into the SIM868 board)</li></ul></div></div>')
o.append('<div class="setup"><h3>SIM868 setup</h3><div class="cols"><ul>'
         '<li><b>Pull the Pico H off</b> the SIM868 board: it is not used. The ESP32-S3 drives the board through 5 M-F jumpers into its Pico sockets: <b>pin 1</b> RXD ← GPIO17, <b>pin 2</b> TXD → GPIO18, <b>pin 3</b> GND, <b>pin 19</b> PWRKEY ← GPIO16, <b>pin 36</b> 3V3 ← ESP32 3V3.</li>'
         '<li>Power it with <b>4.0 V from the step-down</b> (allowed 3.4–4.4 V) into the board’s <b>PH2.0 battery socket</b>, its power slide switch on the battery side. Never 5 V; header pins 39 (VSYS) and 40 (VBUS) stay empty.</li>'
         '<li>Bursts up to 2 A while transmitting: <b>1000 µF</b> at the take-off on the perfboard, short 0.5 mm² leads.</li>'
         '<li>Logic: the board has its own 3.3 V ↔ 2.8 V level shifter (fed from pin 36), so <b>no divider</b> any more.</li></ul><ul>'
         '<li>Power-on: <b>GPIO16 HIGH for 1.5 s</b> (an NPN pulls PWRKEY low), then wait for <b>RDY</b>. NET LED: fast blink = searching, about every 3 s = registered.</li>'
         '<li><b>GSM antenna</b> on the “GSM” u.FL socket before the first power-on. GNSS and BT antennas are not needed.</li>'
         '<li>SIM868 is <b>2G only</b>: Hungary still runs 2G (Telekom’s 2G now runs on Yettel’s network); confirm coverage at the venue.</li>'
         '<li>Turn the SIM PIN off in a phone first; test <b>AT → AT+CPIN? → AT+CREG?</b> and a call before the show.</li></ul></div></div>')
for title, rows in SECTIONS:
    o.append(f'<h2>{esc(title)}</h2><table><thead><tr><th></th><th>Qty</th><th>Part</th><th>Row</th><th>Source</th><th>Purpose</th></tr></thead><tbody>'
             + ''.join(row_html(r) for r in rows) + '</tbody></table>')
o.append('<div class="foot"><div>Second SM-24, if it turns up: same wiring on the Click’s CH2, also with a 1 kΩ resistor across the coil.</div>'
         '<div>Came with the SIM868 but not used: the Raspberry Pi Pico H, the 600 mAh Li-po (the step-down feeds the SIM868), the GNSS and BT antennas. Its small speaker is optional (SIM868 speaker output for two-way talk during the call). Left out on purpose: casing, breadboards, soldering tools, displays, other accelerometers.</div></div>')
o.append('</body></html>')
os.makedirs(OUT, exist_ok=True)
open(os.path.join(OUT, 'parts_list.html'), 'w', encoding='utf-8').write(''.join(o))

# ---- shopping CSV (Hungarian, same columns as before)
FORRAS = {'Hackathon': 'Hackathon', 'Ours': 'SAJÁT', 'Buy': 'VÁSÁROLNI'}
lines = ['Db;Név;Cikkszám;CSV sor;Forrás;Mire kell']
for _, rows in SECTIONS:
    for q, name, code, row, src, _, phu, backup in rows:
        f = FORRAS[src] + (' (tartalék)' if backup else '')
        lines.append(';'.join(str(x).replace(';', ',') for x in (q, name, code, row, f, phu)))
lines += CSV_EXTRA
csv = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'Hackathon_shopping_list_SM24.csv')
open(csv, 'w', encoding='utf-8-sig', newline='\n').write('\n'.join(lines) + '\n')
print('parts list html + csv written,', sum(len(r) for _, r in SECTIONS), 'rows')
