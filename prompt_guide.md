# 🎨 Paper Doll Asset Prompt Guide

A practical reference for generating wardrobe assets using free AI image generators.

---

## 📋 Overview

The workflow is simple:

1. **Generate** a clothing item image using any free AI tool (ChatGPT/DALL-E, Google Gemini, Bing Image Creator).
2. **Drop** the downloaded PNG into the appropriate `raw_imports/` subfolder.
3. **Run** the ingest script to auto-crop, resize, and register the asset.

```
You prompt AI → download PNG → drop in raw_imports/<slot>/ → run ingest script → done
```

This guide helps you write prompts that produce clean, consistent, game-ready clothing sprites.

---

## 🧍 Using the Body Reference

Before prompting, generate a body reference image to share with the AI. This keeps proportions consistent across all your wardrobe pieces.

```bash
./venv/bin/python export_body_ref.py
```

This outputs two versions:

| File | Use Case |
|------|----------|
| `body_ref_transparent.png` | **Edit/inpainting modes** — attach as a base layer for AI to draw clothing onto. Works best with ChatGPT's image editing and similar tools. |
| `body_ref_grid.png` | **General prompting** — attach alongside your text prompt so the AI can see the character's proportions and match them. The grid background prevents the AI from treating it as a transparent overlay. |

**How to use it:**

- **ChatGPT / DALL-E**: Upload the body ref image in the chat, then describe the clothing item you want drawn to fit that body.
- **Gemini**: Attach the grid version with your prompt.
- **Any tool**: Reference it with language like *"Create a clothing item that fits the proportions of the attached character."*

---

## ✅ General Prompting Tips

Follow these rules regardless of which AI tool you use:

### Background
- Always request a **plain white** or **solid white background**.
- Avoid scenes, environments, gradients, or decorative backdrops.
- Example phrase: *"on a plain solid white background"*

### Orientation
- Request **front-facing**, **flat**, **centered on the canvas**.
- The item should be displayed as if laid flat or worn by a mannequin facing forward.
- Avoid 3/4 views, side angles, or perspective distortion.

### Style Keywords
Use these phrases to steer the AI toward game-appropriate output:
- `"2D game character clothing item"`
- `"game sprite asset"`
- `"flat digital illustration style"`
- `"clean lineart with flat coloring"`
- `"paper doll clothing piece"`

### Clothing Only — No Characters
- **Do not** ask for a full character wearing the item.
- Ask for **just the clothing item itself**, as if it were an inventory icon or paper doll cutout.
- Bad: *"A warrior wearing plate armor"*
- Good: *"A plate armor chestpiece, front-facing, flat, 2D game sprite"*

### Proportions
- Always attach or reference the body reference image.
- Add: *"Sized to fit the proportions of the attached character reference."*
- This prevents oversized pauldrons, tiny gloves, or mismatched scale.

### Color & Detail
- Be specific about materials and colors: *"brushed steel with gold trim"* not just *"metal armor."*
- Mention the level of detail you want: *"simple/clean"* for pixel-art style, *"detailed/ornate"* for high-fantasy.

---

## 👕 Slot-Specific Prompt Templates

Copy, paste, and customize these templates. Replace `[DESCRIPTION]` with your specific item.

---

### Topwear (Chest / Torso)

Covers the chest and torso area. Examples: shirts, tunics, armor chestpieces, robes (upper half), vests, corsets, jackets.

```
A [DESCRIPTION] clothing item for the chest and torso area.
Front-facing, flat, centered on a plain solid white background.
2D game sprite asset, clean digital illustration style.
Just the clothing item — no character, no mannequin.
Sized to fit the proportions of the attached character reference.
```

**Example — Leather Vest:**
```
A rugged brown leather vest with visible stitching and brass buckles.
Front-facing, flat, centered on a plain solid white background.
2D game sprite asset, clean digital illustration style.
Just the clothing item — no character, no mannequin.
Sized to fit the proportions of the attached character reference.
```

---

### Bottomwear (Waist / Hips)

Covers the waist and hip area. Examples: skirts, shorts, loincloths, belts, waist armor, sashes, kilts.

```
A [DESCRIPTION] clothing item for the waist and hip area.
Front-facing, flat, centered on a plain solid white background.
2D game sprite asset, clean digital illustration style.
Just the clothing item — no character, no mannequin.
Sized to fit the proportions of the attached character reference.
```

**Example — Chain Mail Skirt:**
```
A knee-length chain mail skirt with a thick leather belt at the waist.
Front-facing, flat, centered on a plain solid white background.
2D game sprite asset, clean digital illustration style.
Just the clothing item — no character, no mannequin.
Sized to fit the proportions of the attached character reference.
```

---

### Legwear (Full Legs)

Covers the legs from thigh to foot. Examples: pants, trousers, boots, greaves, leggings, leg wraps, stockings.

```
A [DESCRIPTION] legwear item covering the legs.
Front-facing, flat, centered on a plain solid white background.
2D game sprite asset, clean digital illustration style.
Just the clothing item — no character, no mannequin.
Sized to fit the proportions of the attached character reference.
```

**Example — Plate Greaves:**
```
Polished steel plate greaves covering both legs from knee to ankle, with knee guards.
Front-facing, flat, centered on a plain solid white background.
2D game sprite asset, clean digital illustration style.
Just the clothing item — no character, no mannequin.
Sized to fit the proportions of the attached character reference.
```

---

### Handwear (Arms / Hands)

Covers the arms and hands. Examples: gloves, gauntlets, bracers, arm wraps, sleeves, rings, wristbands.

```
A [DESCRIPTION] handwear item for the arms and hands.
Front-facing, flat, centered on a plain solid white background.
2D game sprite asset, clean digital illustration style.
Just the clothing items shown as a pair — no character, no mannequin.
Sized to fit the proportions of the attached character reference.
```

**Example — Archer's Bracers:**
```
A pair of dark leather archer's bracers with forearm guards and finger loops.
Front-facing, flat, centered on a plain solid white background.
2D game sprite asset, clean digital illustration style.
Just the clothing items shown as a pair — no character, no mannequin.
Sized to fit the proportions of the attached character reference.
```

---

## ⚔️ RPG Wardrobe Set Suggestions

Five complete themed sets with ready-to-use prompts for every slot.

---

### 🛡️ Warrior Set

A heavy plate armor set fit for a front-line fighter.

**Topwear — Steel Plate Chestpiece:**
```
A heavy steel plate armor chestpiece with riveted shoulder guards and a red cloth tabard underneath. Scratched, battle-worn metal finish.
Front-facing, flat, centered on a plain solid white background.
2D game sprite asset, clean digital illustration style.
Just the clothing item — no character, no mannequin.
Sized to fit the proportions of the attached character reference.
```

**Bottomwear — Armored Tassets:**
```
Steel armored tassets and a wide leather war belt with a sword frog. Metal plates protecting the hips and upper thighs.
Front-facing, flat, centered on a plain solid white background.
2D game sprite asset, clean digital illustration style.
Just the clothing item — no character, no mannequin.
Sized to fit the proportions of the attached character reference.
```

**Legwear — Steel Greaves & Sabatons:**
```
Full steel plate greaves covering both legs from knee to toe, with articulated knee guards and heavy metal sabatons. Battle-worn finish.
Front-facing, flat, centered on a plain solid white background.
2D game sprite asset, clean digital illustration style.
Just the clothing item — no character, no mannequin.
Sized to fit the proportions of the attached character reference.
```

**Handwear — Iron Gauntlets:**
```
A pair of heavy iron gauntlets with articulated finger plates and reinforced knuckles. Scratched steel with leather palm padding.
Front-facing, flat, centered on a plain solid white background.
2D game sprite asset, clean digital illustration style.
Just the clothing items shown as a pair — no character, no mannequin.
Sized to fit the proportions of the attached character reference.
```

---

### 🔮 Mage Set

A mystical set for a spellcaster with arcane embellishments.

**Topwear — Enchanted Robe (Upper):**
```
The upper half of a deep purple wizard's robe with wide sleeves, silver arcane runes embroidered along the hems, and a high stiff collar. Subtle magical glow on the rune details.
Front-facing, flat, centered on a plain solid white background.
2D game sprite asset, clean digital illustration style.
Just the clothing item — no character, no mannequin.
Sized to fit the proportions of the attached character reference.
```

**Bottomwear — Mystic Sash:**
```
A layered cloth sash and waist wrap in deep purple and midnight blue, with a dangling crystal pendant on a silver chain at the hip. Arcane symbols woven into the fabric.
Front-facing, flat, centered on a plain solid white background.
2D game sprite asset, clean digital illustration style.
Just the clothing item — no character, no mannequin.
Sized to fit the proportions of the attached character reference.
```

**Legwear — Enchanted Boots:**
```
Tall soft leather boots in dark violet with silver buckles and faintly glowing arcane sigils etched near the ankles. Pointed toes, knee-height.
Front-facing, flat, centered on a plain solid white background.
2D game sprite asset, clean digital illustration style.
Just the clothing item — no character, no mannequin.
Sized to fit the proportions of the attached character reference.
```

**Handwear — Spellcaster Gloves:**
```
A pair of long fingerless silk gloves in deep purple, extending past the wrist. Glowing arcane circles on the back of each hand, silver thread trim.
Front-facing, flat, centered on a plain solid white background.
2D game sprite asset, clean digital illustration style.
Just the clothing items shown as a pair — no character, no mannequin.
Sized to fit the proportions of the attached character reference.
```

---

### 🗡️ Rogue Set

A stealthy leather set for a shadow-dwelling thief or assassin.

**Topwear — Dark Leather Vest:**
```
A fitted dark charcoal leather vest with a hood attached, multiple small hidden pockets, and dull brass clasps down the front. Worn, supple leather texture.
Front-facing, flat, centered on a plain solid white background.
2D game sprite asset, clean digital illustration style.
Just the clothing item — no character, no mannequin.
Sized to fit the proportions of the attached character reference.
```

**Bottomwear — Utility Belt:**
```
A dark leather utility belt with attached pouches, a dagger sheath on one hip, and small vials in loops. Weathered brown and black leather.
Front-facing, flat, centered on a plain solid white background.
2D game sprite asset, clean digital illustration style.
Just the clothing item — no character, no mannequin.
Sized to fit the proportions of the attached character reference.
```

**Legwear — Shadow Pants & Soft Boots:**
```
Fitted dark gray cloth pants tucked into soft-soled black leather boots. Minimal noise, no metal. Wrapped ankle bindings for stealth movement.
Front-facing, flat, centered on a plain solid white background.
2D game sprite asset, clean digital illustration style.
Just the clothing item — no character, no mannequin.
Sized to fit the proportions of the attached character reference.
```

**Handwear — Fingerless Leather Gloves:**
```
A pair of black fingerless leather gloves with reinforced palms and a thin wrist strap. Subtle grip texture. Stealthy and practical.
Front-facing, flat, centered on a plain solid white background.
2D game sprite asset, clean digital illustration style.
Just the clothing items shown as a pair — no character, no mannequin.
Sized to fit the proportions of the attached character reference.
```

---

### 👑 Noble Set

An elegant aristocratic outfit for courtly encounters.

**Topwear — Embroidered Silk Tunic:**
```
A rich crimson silk tunic with gold embroidered floral patterns, a high mandarin collar, and pearl buttons. Luxurious and regal appearance.
Front-facing, flat, centered on a plain solid white background.
2D game sprite asset, clean digital illustration style.
Just the clothing item — no character, no mannequin.
Sized to fit the proportions of the attached character reference.
```

**Bottomwear — Ornate Waist Sash:**
```
A wide gold-and-white ornate sash wrapped around the waist with a jeweled brooch clasp. Silk tassels hanging at the side. Royal aesthetic.
Front-facing, flat, centered on a plain solid white background.
2D game sprite asset, clean digital illustration style.
Just the clothing item — no character, no mannequin.
Sized to fit the proportions of the attached character reference.
```

**Legwear — Fine Trousers & Court Boots:**
```
Tailored cream-colored silk trousers tucked into polished dark brown leather riding boots with gold filigree buckles. Clean and pristine.
Front-facing, flat, centered on a plain solid white background.
2D game sprite asset, clean digital illustration style.
Just the clothing item — no character, no mannequin.
Sized to fit the proportions of the attached character reference.
```

**Handwear — Jeweled Rings & Silk Gloves:**
```
A pair of white silk gloves extending to mid-forearm, adorned with gold rings set with small rubies on several fingers. Elegant and pristine.
Front-facing, flat, centered on a plain solid white background.
2D game sprite asset, clean digital illustration style.
Just the clothing items shown as a pair — no character, no mannequin.
Sized to fit the proportions of the attached character reference.
```

---

### 🏹 Ranger Set

A rugged outdoorsman set for wilderness survival and archery.

**Topwear — Fur-Trimmed Leather Vest:**
```
A mossy green leather vest with brown fur trim along the collar and shoulders. Laced front closure, worn and weathered texture. Woodsman aesthetic.
Front-facing, flat, centered on a plain solid white background.
2D game sprite asset, clean digital illustration style.
Just the clothing item — no character, no mannequin.
Sized to fit the proportions of the attached character reference.
```

**Bottomwear — Ranger's Belt & Pouches:**
```
A wide brown leather ranger's belt with a quiver hook, herb pouches, and a coil of thin rope. Practical and trail-worn.
Front-facing, flat, centered on a plain solid white background.
2D game sprite asset, clean digital illustration style.
Just the clothing item — no character, no mannequin.
Sized to fit the proportions of the attached character reference.
```

**Legwear — Travel Pants & Rugged Boots:**
```
Sturdy olive-green canvas travel pants tucked into tall brown leather boots with thick soles and calf straps. Mud-splattered, trail-worn.
Front-facing, flat, centered on a plain solid white background.
2D game sprite asset, clean digital illustration style.
Just the clothing item — no character, no mannequin.
Sized to fit the proportions of the attached character reference.
```

**Handwear — Archer's Gloves:**
```
A pair of brown leather archer's gloves with reinforced fingertips on the draw hand and a leather wrist guard on the bow hand. Practical, well-worn.
Front-facing, flat, centered on a plain solid white background.
2D game sprite asset, clean digital illustration style.
Just the clothing items shown as a pair — no character, no mannequin.
Sized to fit the proportions of the attached character reference.
```

---

## 🖥️ Platform-Specific Tips

### ChatGPT / DALL-E

- **Best approach**: Use the **image editing / conversation mode**. Upload `body_ref_transparent.png` and ask ChatGPT to draw the clothing item onto or next to the body.
- After the first good result, say *"Now remove the body and keep only the clothing item on a white background"* for a clean cutout.
- You can iterate: *"Make the armor more ornate"* or *"Change the color to dark blue."*
- ChatGPT remembers context within a conversation — generate an entire set in one chat session for style consistency.
- Use DALL-E 3 (default in ChatGPT) for best quality.

### Google Gemini

- Attach `body_ref_grid.png` with your prompt.
- Gemini responds well to detailed, structured prompts — use the full templates above.
- Specify *"Do not include any text or watermarks in the image."*
- If Gemini adds a character, re-prompt with: *"Show only the clothing item by itself, no person or mannequin."*
- Gemini may produce multiple options — pick the cleanest one with the most solid white background.

### Bing Image Creator (DALL-E powered)

- No image upload supported — you cannot attach a body reference.
- Compensate by being very specific about proportions: *"medium build adult humanoid, approximately 6 heads tall."*
- Add *"digital art, game asset, white background, no text"* to every prompt.
- Bing generates 4 images at once — pick the most centered, cleanest result.
- For style consistency across a set, use nearly identical prompt structures and only change the item description.

### Any Free Model (General)

- Always download the **highest resolution** version available.
- Save as **PNG** (not JPEG) to preserve transparency and sharp edges.
- If the AI adds unwanted elements (text, watermarks, extra objects), try adding *"no text, no watermark, no extra objects, clean isolated item"* to your prompt.
- Generate 2–3 variations and pick the best one rather than trying to get a perfect result on the first try.
- If proportions are off, try a different phrasing or re-attach the body reference.

---

## 📁 Folder Organization

Place your downloaded images into the correct subfolder under `raw_imports/`:

```
raw_imports/
├── topwear/
│   ├── leather_armor.png
│   ├── wizard_robe.png
│   └── silk_tunic.png
├── bottomwear/
│   ├── plate_skirt.png
│   ├── utility_belt.png
│   └── ornate_sash.png
├── legwear/
│   ├── iron_boots.png
│   ├── travel_pants.png
│   └── enchanted_boots.png
└── handwear/
    ├── iron_gauntlets.png
    ├── fingerless_gloves.png
    └── archer_bracers.png
```

### Naming Convention

The filename becomes the in-game display name:

| Filename | Display Name |
|----------|-------------|
| `leather_armor.png` | Leather Armor |
| `iron_boots.png` | Iron Boots |
| `wizard_robe.png` | Wizard Robe |
| `enchanted_boots.png` | Enchanted Boots |

**Rules:**
- Use **lowercase** with **underscores** for spaces.
- Keep names short and descriptive.
- Avoid special characters — stick to `a-z`, `0-9`, and `_`.
- File must be `.png` format.

---

## ⌨️ Quick Command Reference

```bash
# Export body reference images (transparent + grid versions)
./venv/bin/python export_body_ref.py

# Process all raw imports (crop, resize, register)
./venv/bin/python ingest_assets.py
```

---

## 💡 Troubleshooting

| Problem | Solution |
|---------|----------|
| AI draws a full character instead of just clothing | Add *"just the clothing item, no character, no mannequin, no person"* |
| Background isn't clean white | Add *"plain solid white background, no gradients, no shadows"* |
| Item is too small / too large | Attach the body reference and add *"sized to fit the attached reference"* |
| Style is inconsistent across pieces | Generate all pieces of a set in one session; reuse identical style phrases |
| AI adds text or watermarks | Add *"no text, no labels, no watermarks"* to prompt |
| Proportions look wrong after ingest | Re-generate with body ref attached; check the slot is correct |

---

*Generated for the Paper Doll wardrobe system. Keep this file handy while prompting — copy templates, swap in your descriptions, and build your wardrobe library.*
