export function cloneImageData(imageData) {
  const data = new Uint8ClampedArray(imageData.data);
  if (typeof ImageData === 'function') {
    return new ImageData(data, imageData.width, imageData.height);
  }
  return { data, width: imageData.width, height: imageData.height };
}

export function parseHexColor(hex) {
  const clean = (hex || '#ffffff').replace('#', '');
  if (clean.length !== 6) return [255, 255, 255];
  return [
    parseInt(clean.slice(0, 2), 16),
    parseInt(clean.slice(2, 4), 16),
    parseInt(clean.slice(4, 6), 16),
  ];
}

export function removeColorKey(imageData, rgb, tolerance) {
  const out = cloneImageData(imageData);
  const data = out.data;
  const [kr, kg, kb] = rgb;
  for (let i = 0; i < data.length; i += 4) {
    if (data[i + 3] === 0) continue;
    const dr = data[i] - kr;
    const dg = data[i + 1] - kg;
    const db = data[i + 2] - kb;
    const dist = Math.sqrt(dr * dr + dg * dg + db * db);
    if (dist <= tolerance) data[i + 3] = 0;
  }
  return out;
}

export function removeWhiteBackground(imageData, tolerance) {
  return removeColorKey(imageData, [255, 255, 255], tolerance);
}

export function applyAlphaThreshold(imageData, threshold) {
  const out = cloneImageData(imageData);
  const data = out.data;
  for (let i = 0; i < data.length; i += 4) {
    data[i + 3] = data[i + 3] >= threshold ? 255 : 0;
  }
  return out;
}

export function cleanupHalo(imageData) {
  const out = cloneImageData(imageData);
  const data = out.data;
  for (let i = 0; i < data.length; i += 4) {
    const a = data[i + 3];
    if (a === 0) {
      data[i] = 0;
      data[i + 1] = 0;
      data[i + 2] = 0;
    } else if (a < 220) {
      data[i + 3] = Math.max(0, a - 35);
    }
  }
  return out;
}

function collectComponents(imageData, minAlpha = 10) {
  const { width, height, data } = imageData;
  const visited = new Uint8Array(width * height);
  const components = [];
  const queue = [];

  for (let start = 0; start < width * height; start++) {
    if (visited[start] || data[start * 4 + 3] <= minAlpha) continue;
    const pixels = [];
    visited[start] = 1;
    queue.length = 0;
    queue.push(start);

    for (let qi = 0; qi < queue.length; qi++) {
      const idx = queue[qi];
      pixels.push(idx);
      const x = idx % width;
      const y = Math.floor(idx / width);
      const neighbors = [
        x > 0 ? idx - 1 : -1,
        x < width - 1 ? idx + 1 : -1,
        y > 0 ? idx - width : -1,
        y < height - 1 ? idx + width : -1,
      ];
      for (const n of neighbors) {
        if (n < 0 || visited[n] || data[n * 4 + 3] <= minAlpha) continue;
        visited[n] = 1;
        queue.push(n);
      }
    }
    components.push(pixels);
  }

  return components;
}

export function keepLargestConnectedComponent(imageData, minAlpha = 10) {
  const out = cloneImageData(imageData);
  const components = collectComponents(out, minAlpha);
  if (components.length <= 1) return out;
  let largest = components[0];
  for (const component of components) {
    if (component.length > largest.length) largest = component;
  }
  const keep = new Uint8Array(out.width * out.height);
  for (const idx of largest) keep[idx] = 1;
  for (let i = 0; i < keep.length; i++) {
    if (!keep[i]) out.data[i * 4 + 3] = 0;
  }
  return out;
}

export function removeSmallIslands(imageData, minArea = 32, minAlpha = 10) {
  const out = cloneImageData(imageData);
  const components = collectComponents(out, minAlpha);
  for (const component of components) {
    if (component.length >= minArea) continue;
    for (const idx of component) out.data[idx * 4 + 3] = 0;
  }
  return out;
}

export function getAlphaStats(imageData) {
  const { width, height, data } = imageData;
  let opaquePixels = 0;
  let semiTransparentPixels = 0;
  let minX = width;
  let minY = height;
  let maxX = -1;
  let maxY = -1;
  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      const i = (y * width + x) * 4;
      const a = data[i + 3];
      if (a > 10) {
        opaquePixels++;
        if (a < 245) semiTransparentPixels++;
        if (x < minX) minX = x;
        if (x > maxX) maxX = x;
        if (y < minY) minY = y;
        if (y > maxY) maxY = y;
      }
    }
  }
  const bbox = maxX === -1 ? null : { x: minX, y: minY, width: maxX - minX + 1, height: maxY - minY + 1 };
  return {
    opaquePixels,
    semiTransparentPixels,
    coverage: opaquePixels / (width * height),
    bbox,
  };
}

export function countVisibleMaskOverlap(imageData, maskImageData, minAlpha = 10) {
  const len = Math.min(imageData.data.length, maskImageData.data.length);
  let overlap = 0;
  let visible = 0;
  for (let i = 0; i < len; i += 4) {
    if (imageData.data[i + 3] > minAlpha) {
      visible++;
      if (maskImageData.data[i + 3] > minAlpha) overlap++;
    }
  }
  return { overlap, visible };
}
