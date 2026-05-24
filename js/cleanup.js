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

export function applyMaskProposal(currentImageData, proposalImageData, sourceImageData, mode = 'replace') {
  const out = cloneImageData(currentImageData);
  const len = Math.min(out.data.length, proposalImageData.data.length, sourceImageData.data.length);
  for (let i = 0; i < len; i += 4) {
    const currentAlpha = currentImageData.data[i + 3];
    const proposalAlpha = proposalImageData.data[i + 3];
    let nextAlpha = proposalAlpha;
    if (mode === 'union') nextAlpha = Math.max(currentAlpha, proposalAlpha);
    if (mode === 'intersect') nextAlpha = Math.min(currentAlpha, proposalAlpha);

    if (nextAlpha > 0) {
      const sourceVisible = sourceImageData.data[i + 3] > 0;
      out.data[i] = sourceVisible ? sourceImageData.data[i] : proposalImageData.data[i];
      out.data[i + 1] = sourceVisible ? sourceImageData.data[i + 1] : proposalImageData.data[i + 1];
      out.data[i + 2] = sourceVisible ? sourceImageData.data[i + 2] : proposalImageData.data[i + 2];
    }
    out.data[i + 3] = nextAlpha;
  }
  return out;
}

function newMaskImageData(data, width, height) {
  if (typeof ImageData === 'function') {
    return new ImageData(data, width, height);
  }
  return { data, width, height };
}

function maskAlphaAt(mask, pixelIndex) {
  return mask?.data?.[pixelIndex * 4 + 3] || 0;
}

function setMaskAlpha(data, pixelIndex, alpha) {
  const i = pixelIndex * 4;
  data[i] = 255;
  data[i + 1] = 255;
  data[i + 2] = 255;
  data[i + 3] = alpha;
}

function normalizeClipMode(mode) {
  if (mode === 'soft_clip' || mode === 'soft') return 'soft_clip';
  if (mode === 'strict_clip' || mode === 'strict') return 'strict_clip';
  return 'preview_only';
}

export function dilateMask(mask, px = 1, minAlpha = 10) {
  const radius = Math.max(0, Math.round(px));
  const out = new Uint8ClampedArray(mask.width * mask.height * 4);
  if (radius === 0) return cloneImageData(mask);
  for (let y = 0; y < mask.height; y++) {
    for (let x = 0; x < mask.width; x++) {
      let visible = false;
      for (let yy = Math.max(0, y - radius); yy <= Math.min(mask.height - 1, y + radius) && !visible; yy++) {
        for (let xx = Math.max(0, x - radius); xx <= Math.min(mask.width - 1, x + radius); xx++) {
          if (maskAlphaAt(mask, yy * mask.width + xx) > minAlpha) {
            visible = true;
            break;
          }
        }
      }
      if (visible) setMaskAlpha(out, y * mask.width + x, 255);
    }
  }
  return newMaskImageData(out, mask.width, mask.height);
}

export function erodeMask(mask, px = 1, minAlpha = 10) {
  const radius = Math.max(0, Math.round(px));
  const out = new Uint8ClampedArray(mask.width * mask.height * 4);
  if (radius === 0) return cloneImageData(mask);
  for (let y = 0; y < mask.height; y++) {
    for (let x = 0; x < mask.width; x++) {
      let visible = true;
      for (let yy = y - radius; yy <= y + radius && visible; yy++) {
        for (let xx = x - radius; xx <= x + radius; xx++) {
          if (xx < 0 || yy < 0 || xx >= mask.width || yy >= mask.height || maskAlphaAt(mask, yy * mask.width + xx) <= minAlpha) {
            visible = false;
            break;
          }
        }
      }
      if (visible) setMaskAlpha(out, y * mask.width + x, 255);
    }
  }
  return newMaskImageData(out, mask.width, mask.height);
}

export function featherMask(mask, px = 1, minAlpha = 10) {
  const radius = Math.max(0, Math.round(px));
  if (radius === 0) return cloneImageData(mask);
  const out = new Uint8ClampedArray(mask.width * mask.height * 4);
  const diameter = radius * 2 + 1;
  const maxSamples = diameter * diameter;
  for (let y = 0; y < mask.height; y++) {
    for (let x = 0; x < mask.width; x++) {
      let visibleSamples = 0;
      for (let yy = y - radius; yy <= y + radius; yy++) {
        for (let xx = x - radius; xx <= x + radius; xx++) {
          if (xx < 0 || yy < 0 || xx >= mask.width || yy >= mask.height) continue;
          if (maskAlphaAt(mask, yy * mask.width + xx) > minAlpha) visibleSamples++;
        }
      }
      if (visibleSamples > 0) {
        setMaskAlpha(out, y * mask.width + x, Math.round((visibleSamples / maxSamples) * 255));
      }
    }
  }
  return newMaskImageData(out, mask.width, mask.height);
}

export function buildBodyStencil(bodyMask, allowedMask = null, forbiddenMasks = [], options = {}) {
  const width = bodyMask.width;
  const height = bodyMask.height;
  const minAlpha = options.minAlpha ?? 10;
  const out = new Uint8ClampedArray(width * height * 4);
  for (let pixel = 0; pixel < width * height; pixel++) {
    const bodyVisible = maskAlphaAt(bodyMask, pixel) > minAlpha;
    const allowedVisible = !allowedMask || maskAlphaAt(allowedMask, pixel) > minAlpha;
    let forbiddenVisible = false;
    for (const forbidden of forbiddenMasks || []) {
      if (forbidden && maskAlphaAt(forbidden, pixel) > minAlpha) {
        forbiddenVisible = true;
        break;
      }
    }
    if (bodyVisible && allowedVisible && !forbiddenVisible) {
      setMaskAlpha(out, pixel, 255);
    }
  }

  let stencil = newMaskImageData(out, width, height);
  const expandPx = Math.round(options.expandPx ?? options.expand_px ?? 0);
  if (expandPx > 0) stencil = dilateMask(stencil, expandPx, minAlpha);
  if (expandPx < 0) stencil = erodeMask(stencil, Math.abs(expandPx), minAlpha);
  const featherPx = Math.round(options.featherPx ?? options.feather_px ?? 0);
  if (featherPx > 0) stencil = featherMask(stencil, featherPx, minAlpha);
  return stencil;
}

function smallOutsideDetailMask(imageData, stencilMask, maxArea = 64, minAlpha = 10) {
  const { width, height, data } = imageData;
  const visited = new Uint8Array(width * height);
  const preserve = new Uint8Array(width * height);
  const queue = [];
  for (let start = 0; start < width * height; start++) {
    if (visited[start] || data[start * 4 + 3] <= minAlpha || maskAlphaAt(stencilMask, start) > minAlpha) continue;
    const pixels = [];
    let touchesStencil = false;
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
        if (n < 0) continue;
        if (maskAlphaAt(stencilMask, n) > minAlpha) touchesStencil = true;
        if (!visited[n] && data[n * 4 + 3] > minAlpha && maskAlphaAt(stencilMask, n) <= minAlpha) {
          visited[n] = 1;
          queue.push(n);
        }
      }
    }
    if (touchesStencil && pixels.length <= maxArea) {
      for (const idx of pixels) preserve[idx] = 1;
    }
  }
  return preserve;
}

export function applyStencilClip(imageData, stencilMask, mode = 'preview_only', options = {}) {
  const clipMode = normalizeClipMode(mode);
  if (clipMode === 'preview_only' || !stencilMask) return cloneImageData(imageData);
  const out = cloneImageData(imageData);
  const minAlpha = options.minAlpha ?? 10;
  const preserveSmallDetails = !!(options.preserveSmallDetails ?? options.preserve_small_details);
  const preserved = preserveSmallDetails ? smallOutsideDetailMask(imageData, stencilMask, options.smallDetailMaxArea || 64, minAlpha) : null;
  const len = Math.min(out.width * out.height, stencilMask.width * stencilMask.height);
  for (let pixel = 0; pixel < len; pixel++) {
    const i = pixel * 4;
    if (out.data[i + 3] <= minAlpha) continue;
    const stencilAlpha = maskAlphaAt(stencilMask, pixel);
    if (stencilAlpha <= minAlpha) {
      if (!preserved?.[pixel]) out.data[i + 3] = 0;
    } else if (clipMode === 'soft_clip') {
      out.data[i + 3] = Math.min(out.data[i + 3], Math.round(out.data[i + 3] * (stencilAlpha / 255)));
    }
  }
  return out;
}

export function computeOutsideStencilRatio(imageData, stencilMask, minAlpha = 10) {
  const len = Math.min(imageData.width * imageData.height, stencilMask.width * stencilMask.height);
  let visible = 0;
  let outside = 0;
  for (let pixel = 0; pixel < len; pixel++) {
    if (imageData.data[pixel * 4 + 3] > minAlpha) {
      visible++;
      if (maskAlphaAt(stencilMask, pixel) <= minAlpha) outside++;
    }
  }
  return visible > 0 ? outside / visible : 0;
}

export function buildCleanupMetadata({ sourceLane, operations = [], manualEdits = 0, mlAssist = null, stencil = null } = {}) {
  const metadata = {
    source_lane: sourceLane || 'transparent_png',
    operations: [...operations],
    manual_edits: manualEdits,
  };
  if (mlAssist) {
    metadata.ml_assist = {
      backend: mlAssist.backend || 'cv',
      style_strength: mlAssist.style_strength,
      apply_mode: mlAssist.apply_mode,
      proposal_stats: mlAssist.proposal_stats || null,
    };
  }
  if (stencil) {
    metadata.stencil = {
      enabled: !!stencil.enabled,
      source: stencil.source || 'body_silhouette',
      project_layer_id: stencil.project_layer_id || null,
      project_layer_name: stencil.project_layer_name || null,
      custom_stencil_id: stencil.custom_stencil_id || null,
      custom_stencil_name: stencil.custom_stencil_name || null,
      mode: normalizeClipMode(stencil.mode),
      expand_px: Number(stencil.expand_px ?? stencil.expandPx ?? 0),
      feather_px: Number(stencil.feather_px ?? stencil.featherPx ?? 0),
      use_allowed_region: stencil.use_allowed_region !== false,
      subtract_forbidden_regions: stencil.subtract_forbidden_regions !== false,
      preserve_small_details: !!(stencil.preserve_small_details ?? stencil.preserveSmallDetails),
    };
  }
  return metadata;
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
