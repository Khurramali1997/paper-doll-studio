export const KEYWORDS = {
  hair: ['hair', 'bang', 'fringe', 'tail'],
  eyes: ['eye', 'iris', 'brow', 'lash', 'white'],
  face: ['face', 'neck', 'ears', 'nose', 'mouth', 'body', 'torso', 'skin', 'head'],
  wardrobe: ['wear', 'cloth', 'top', 'bottom', 'leg', 'hand', 'glove', 'pants', 'shirt', 'skirt', 'shoe', 'sock']
};

// Order matters: more specific slots come first so "footwear" matches `shoes`
// before it falls through to `legwear`'s `leg` keyword, etc.
export const WARDROBE_SLOTS = {
  shoes: ['shoe', 'boot', 'footwear', 'foot', 'feet'],
  handwear: ['hand', 'glove', 'arm', 'sleeve'],
  topwear: ['top', 'shirt', 'jacket', 'vest', 'coat', 'chest'],
  bottomwear: ['bottom', 'underwear', 'waist'],
  skirt: ['skirt'],
  pants: ['pant', 'trouser', 'jean'],
  legwear: ['leg', 'sock', 'legging', 'stocking', 'tight'],
};

export function cleanLayerName(name) {
  return name.toLowerCase().trim().replace(/\s+/g, '_').replace(/-/g, '_');
}

export function getCategory(cleanName) {
  if (KEYWORDS.wardrobe.some(w => cleanName.includes(w))) return 'wardrobe';
  if (KEYWORDS.hair.some(w => cleanName.includes(w))) return 'hair';
  if (KEYWORDS.eyes.some(w => cleanName.includes(w))) return 'eyes';
  return 'face';
}

export function getWardrobeSlot(cleanName) {
  for (const [slot, kws] of Object.entries(WARDROBE_SLOTS)) {
    if (kws.some(kw => cleanName.includes(kw))) return slot;
  }
  return 'accessories';
}

export function getOptionValue(cleanName, slot, psdFileName = null) {
  const skinKeywords = ['skin_wear', 'naked'];
  if (skinKeywords.some(k => cleanName.includes(k)) || cleanName === slot) return 'skin_wear';
  if (cleanName.includes('clothing') || cleanName.includes('clothed')) return 'clothing';

  let val = cleanName;
  const toRemove = [slot, 'wear', 'cloth', 'l', 'r', 'left', 'right'];
  if (WARDROBE_SLOTS[slot]) {
    toRemove.push(...WARDROBE_SLOTS[slot]);
  }
  for (const word of toRemove) {
    val = val.split(word).join('');
  }
  val = val.replace(/^_+|_+$/g, '');

  if (!val) {
    if (psdFileName) {
      const fnLower = psdFileName.toLowerCase();
      if (fnLower.includes('clothed') || fnLower.includes('clothing')) return 'clothing';
      if (fnLower.includes('naked') || fnLower.includes('skin')) return 'skin_wear';
    }
    if (cleanName === slot ||
        cleanName.endsWith('_l') || cleanName.endsWith('_r') ||
        cleanName.endsWith('_left') || cleanName.endsWith('_right')) {
      return 'skin_wear';
    }
    return 'default';
  }
  return val;
}

export function canvasToBlob(canvas) {
  return new Promise(resolve => canvas.toBlob(resolve, 'image/png'));
}

export function loadImage(src) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.crossOrigin = 'anonymous';
    img.onload = () => resolve(img);
    img.onerror = () => reject(new Error('Failed to load image: ' + src));
    img.src = src;
  });
}

export function getBoundingBox(canvas) {
  const ctx = canvas.getContext('2d');
  const imgData = ctx.getImageData(0, 0, canvas.width, canvas.height);
  const data = imgData.data;
  const width = canvas.width;
  const height = canvas.height;

  let minX = width, maxX = -1, minY = height, maxY = -1;

  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      const idx = (y * width + x) * 4;
      if (data[idx + 3] > 10) {
        if (x < minX) minX = x;
        if (x > maxX) maxX = x;
        if (y < minY) minY = y;
        if (y > maxY) maxY = y;
      }
    }
  }

  if (maxX === -1 || maxY === -1) return null;
  return { x: minX, y: minY, width: maxX - minX + 1, height: maxY - minY + 1 };
}

export function applyChromaKey(canvas, keyColorHex, tolerance) {
  const ctx = canvas.getContext('2d');
  const imgData = ctx.getImageData(0, 0, canvas.width, canvas.height);
  const data = imgData.data;

  const rKey = parseInt(keyColorHex.substring(1, 3), 16);
  const gKey = parseInt(keyColorHex.substring(3, 5), 16);
  const bKey = parseInt(keyColorHex.substring(5, 7), 16);

  for (let i = 0; i < data.length; i += 4) {
    if (data[i + 3] === 0) continue;
    const dist = Math.sqrt(
      (data[i] - rKey) ** 2 +
      (data[i + 1] - gKey) ** 2 +
      (data[i + 2] - bKey) ** 2
    );
    if (dist < tolerance) {
      data[i + 3] = 0;
    }
  }
  ctx.putImageData(imgData, 0, 0);
}

export function isHandwearRight(id, name) {
  return id.endsWith('_r') || id.endsWith('_right') ||
         name.toLowerCase().endsWith('_r') || name.toLowerCase().endsWith('_right') ||
         id.includes('_r_') || id.includes('_right_');
}

export function isHandwearLeft(id, name) {
  return id.endsWith('_l') || id.endsWith('_left') ||
         name.toLowerCase().endsWith('_l') || name.toLowerCase().endsWith('_left') ||
         id.includes('_l_') || id.includes('_left_');
}

export function computeBakeGeometry(imgW, imgH, docW, docH, align) {
  const w = imgW * align.scaleX;
  const h = imgH * align.scaleY;
  const cx = docW / 2 + align.x;
  const cy = docH / 2 + align.y;
  return { left: cx - w / 2, top: cy - h / 2, width: w, height: h };
}

export function applyBakeTransform(ctx, img, docW, docH, align) {
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.translate(docW / 2 + align.x, docH / 2 + align.y);
  ctx.scale(align.scaleX, align.scaleY);
  ctx.drawImage(img, -img.width / 2, -img.height / 2);
}

export function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}
