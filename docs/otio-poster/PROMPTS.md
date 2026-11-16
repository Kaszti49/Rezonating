# OTIO poster: image prompts

Four AI images. Save each into `docs/otio-poster/images/` as `H.jpg`, `B.png`, `D.jpg`, `E.jpg`
(jpg, png or webp all work), then run `python docs/otio-poster/build.py`. The build reports each
image's print resolution and fails below 60 px/cm, the organizer's 150 dpi rule.

## Rules for every image

- **No text, labels, logos or UI in the image.** The poster adds all type and callouts. Generators
  misspell Hungarian.
- **The one accent color is orange (#F0641E).** It appears only as the device's status LED. Everything
  else stays low-saturation: charcoal, warm grey, oak.
- **Use the same device in every image.** Paste the device block into each prompt. Generate H first,
  then give it as a reference image (image prompt / style reference) for B, D and E.
- **Resolution.** Generate at the largest size the tool offers, then upscale 4× (Upscayl, free on
  Windows, "Real-ESRGAN" model; Midjourney "Upscale (Creative)"; Krea or Magnific). The hero needs
  **at least 5700 × 2340 px**.
- **Label.** The poster states that the photos are AI illustrations (under Szakirodalom). Keep that
  line, because the brief asks for a source for every image you didn't make yourself.

### Device block (paste into every prompt)

The real casing: round, 19 cm across, about 5.5 cm tall with the lid. Both geophones are **inside**.

> a single low round sensor puck lying flat on the floor, 19 cm across and 5 cm tall, like a thick
> coaster or a small robot-vacuum dock, matte charcoal-grey 3D-printed housing with fine horizontal
> print layer lines, a slightly domed matte lid with a thin glossy black ring around its edge, one tiny
> glowing orange status LED on the side, one thin black USB cable leaving the back; nothing else is
> attached to it, no sensors outside the housing

---

## H: hero (full width under the title)

- **Printed size:** 950 × 390 mm, full bleed. **Aspect ratio 2:1** (the layout crops a little from
  the top and bottom). **Minimum 5700 × 2340 px.**
- **Composition:** the device sits in the **right third**, in sharp focus. A shoe lands on the floor in
  the **left third**, in soft focus. Keep the **upper left dark and empty** (negative space). The poster
  puts two callouts on it: "Lépés" (step) points at the shoe, "Csomópont" (node) at the device.

**Prompt**
> Editorial advertising product photograph, ultra-wide 2:1, camera at floor level. A dark, quiet
> living room at night with a warm oak plank floor. In the right third, in sharp focus: [device block].
> In the left third, out of focus and much larger in frame, a person's foot in a clean dark-grey leather
> sneaker is mid-step, the heel just touching the oak floor; only the shoe and the ankle are visible,
> the trouser hem in charcoal wool. From the heel, very faint concentric ripples spread across the
> wood surface like the surface of water, catching the light as delicate caustics and travelling
> toward the device. Chiaroscuro, Rembrandt lighting from a single soft key light at the upper right,
> a crisp edge rim light outlining both the shoe and the device, deep ambient occlusion where the
> device meets the floor, subtle vignetting. Large dark negative space in the upper left. Asymmetrical
> balance, rule of thirds, strong scale contrast between the large blurred shoe and the small sharp
> device. Matte housing against a glossy lid ring and a glossy lacquered floor. Low-saturation
> monochromatic charcoal and warm oak palette, the only saturated color is the tiny orange LED. Shot
> on a medium-format camera, 80 mm lens, f/2.8, fine tactile film grain, photorealistic, high detail.

**Negative prompt** (if the tool has one)
> text, letters, logo, brand logo on the shoe, watermark, UI, screen, cartoon, illustration, CGI look,
> plastic toy, neon, blue light, oversaturated, cluttered background, face, bare feet, sensors or
> cables lying outside the device

---

## B: the Rezon taken apart (left of the waveform strip)

- **Printed size:** 250 × 132 mm on the light grey strip. **Aspect ratio 16:9.** **Minimum
  1500 × 800 px.**
- **Pure white background, on purpose.** The poster multiplies the image into the grey strip, so the
  white disappears and only the parts and their soft shadows stay. That reads as an object on paper,
  not as a photo in a box.
- **Callouts come from the poster, top to bottom:** Fedél (lid), ESP32-S3, ADC 24 bit, 2× SM-24
  geophone, Ház Ø 19 cm (housing). Keep the parts in that order, with clear space to the left and
  right of the stack. I move the labels onto the real parts once the image is in.

**Prompt (exploded view, recommended)**
> Photorealistic exploded-view product photograph of a round floor vibration sensor, editorial
> advertising style, on a pure seamless white background. The parts float in a vertical stack along
> one axis, evenly spaced, seen from a three-quarter view slightly above. From top to bottom: a round
> matte charcoal-grey 3D-printed lid 19 cm across with a thin glossy black edge ring; a small black
> microcontroller development board, 6 cm long, with a metal-shielded radio module and pin headers; a
> smaller black analog-to-digital converter board, 4 cm long, with a green screw terminal block; two
> identical small black metal cylinders, 2.5 cm across and 3 cm tall, side by side, with two gold
> solder terminals on top (geophone sensors); at the bottom, the round open 3D-printed base 19 cm
> across, matte charcoal with fine print layer lines, showing its inner walls and two round pockets
> that hold the cylinders. One tiny orange LED glows on the microcontroller board. Precise, clean,
> engineered look, generous negative space on the left and right of the stack, soft high-key studio
> light with a gentle edge rim light on every part, soft ambient occlusion shadows under each part,
> matte plastic against glossy metal and circuit boards. Low-saturation charcoal and white palette,
> the only saturated color is the orange LED. 100 mm lens, f/8, everything in focus, photorealistic,
> high detail, no text, no labels, no lines, no arrows.

**Prompt (alternative: open lid, top view)** if the exploded view comes out messy
> Photorealistic top-down product photograph, flat lay, editorial advertising style, on a pure
> seamless white background. A round matte charcoal-grey 3D-printed sensor housing 19 cm across,
> lid removed and lying beside it at the upper right, tilted to show its underside. Inside the open
> housing, neatly arranged and fixed to the floor: two small black metal cylinders 2.5 cm across
> (geophone sensors) in round pockets on opposite sides, a small black microcontroller board with a
> metal-shielded module in the middle, a smaller black converter board next to it, short tidy black
> wires between them. One tiny orange LED glows on the board. Soft high-key light from above, gentle
> ambient occlusion inside the housing walls, fine print layer lines visible, matte plastic against
> glossy boards. Generous negative space around the object. Low-saturation charcoal and white
> palette, the only saturated color is the orange LED. Photorealistic, high detail, no text, no
> labels, no lines, no arrows.

**Negative prompt**
> text, labels, arrows, leader lines, blueprint grid, blue tint, colored circuit boards (blue, red,
> green), cables floating loose, extra parts, batteries, screens, logo, watermark, cartoon

---

## D: use case, elder care (above 05 Hasznosíthatóság)

- **Printed size:** 278 × 140 mm. **Aspect ratio 2:1.** **Minimum 1700 × 850 px.**

**Prompt**
> Editorial lifestyle photograph for a premium smart-home product, wide 2:1. A grandmother in her late
> seventies walks calmly down a warm hallway of an apartment in the evening, seen from floor level at a
> distance, her soft house shoes and lower legs in focus, her face out of frame. In the foreground on
> the oak floor, beside the skirting board: [device block], small in the frame. Warm low light from a
> doorway on one side (Rembrandt lighting), soft subsurface scattering in a linen curtain, deep
> shadows, subtle vignetting. Calm, safe and dignified mood, not a hospital. Rule of thirds, generous
> negative space, low-saturation warm grey palette, the only saturated color is the orange LED. 35 mm
> lens, f/2, fine film grain, photorealistic, no text.

---

## E: instead of a camera (above 04 Újdonság, innováció)

- **Printed size:** 278 × 140 mm. **Aspect ratio 2:1.** **Minimum 1700 × 850 px.**
- **Idea:** privacy. A home security camera is switched off, unplugged and set aside, and the small
  floor device is doing its job.

**Prompt**
> Still-life product photograph, editorial advertising style, wide 2:1. On a dark oak floor, in the
> foreground right third in sharp focus: [device block]. Behind it, out of focus on a low shelf, a
> white home security camera lies on its side, unplugged, its cable coiled, its lens covered by a
> small piece of matte tape. Chiaroscuro lighting, one soft key light from the left, edge rim light on
> the device, ambient occlusion, subtle vignetting. Strong scale contrast and asymmetrical balance,
> large negative space at the top. Matte versus glossy contrast between the tape, the plastic camera
> and the device's lid ring. Low-saturation charcoal, white and oak palette, the only saturated color
> is the orange LED. 50 mm lens, f/2.8, fine film grain, photorealistic, no text, no brand logos.

---

## After generating

1. Check the device looks the same in H, D and E, and that nothing sticks out of it. If one drifts,
   regenerate it with H as the reference.
2. Put the files in `images/` and run the build. I then move the callouts onto the real shoe, device
   and parts, and fix the crop of each image.
