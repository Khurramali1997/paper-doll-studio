import { state, DOLL_CONFIG, TOGGLE_GROUPS, pushHistory } from './state.js';
import {
  renderDoll, pendingAssetFile, pendingAssetImage, pendingPreviewImage, pendingPreviewIsBaked,
  setPendingAsset, setPendingPreviewImage, clearImageCache, cacheImage, alignSettings,
  generateDynamicBodyReferenceCanvas, updateDollCursor, updateViewportTransform
} from './render.js';
import {
  cleanLayerName, getCategory, getWardrobeSlot, getOptionValue,
  canvasToBlob, loadImage, getBoundingBox, applyChromaKey,
  applyBakeTransform
} from './utils.js';
import {
  cloneImageData as cloneCleanupImageData,
  removeWhiteBackground,
  removeColorKey,
  applyAlphaThreshold,
  cleanupHalo,
  keepLargestConnectedComponent,
  removeSmallIslands,
  getAlphaStats as getCleanupAlphaStats,
  parseHexColor,
  countVisibleMaskOverlap,
} from './cleanup.js';
import { clearFitPreview } from './fit_preview.js';
import { buildUI, updateActiveOptionButton } from './wardrobe.js';
import { buildCalibrateOptions, updateCalibrateUI } from './calibration.js';

let mlBgModule = null;

const cleanupState = {
  initialized: false,
  sourceCanvas: null,
  sourceImageData: null,
  candidateCanvas: null,
  candidateImageData: null,
  manualMaskImageData: null,
  undoStack: [],
  manualEdits: 0,
  operations: [],
  sourceLane: 'transparent_png',
  brushDown: false,
  brushTool: 'erase',
  activeMaskCache: {},
};

// ===== AI Isolation cache + live preview =====
// One cached AI-processed image per source. When the user toggles modes,
// we only re-POST to the backend if the source or mode changed.
let aiProcessedCache = null;  // { sourceKey, mode, blob, objectUrl, image }
let livePreviewTargetContainer = null;
let livePreviewScheduled = false;
let livePreviewRendering = false;
let livePreviewDirty = false;

const MIN_AI_ALPHA_COVERAGE = 0.002;
const MIN_AI_OPAQUE_PIXELS = 128;

function _sourceKey() {
  const f = pendingAssetFile;
  if (!f) return null;
  return `${f.name}::${f.size}::${f.lastModified || ''}`;
}

async function ensureAIProcessed(mode) {
  if (!pendingAssetFile || mode === 'off') return null;
  const key = _sourceKey();
  if (aiProcessedCache?.sourceKey === key && aiProcessedCache?.mode === mode) {
    return aiProcessedCache.image;
  }
  const status = document.getElementById('ai-isolation-status');
  if (status) { status.style.display = 'block'; status.textContent = 'Processing... (first run downloads model)'; }
  const fd = new FormData();
  fd.append('image', pendingAssetFile);
  fd.append('mode', mode);
  const res = await fetch('/api/ai-process', { method: 'POST', body: fd });
  if (!res.ok) {
    if (status) { status.textContent = `Failed (${res.status})`; status.style.color = 'var(--danger-color)'; }
    throw new Error(`AI processing failed (${res.status})`);
  }
  const blob = await res.blob();
  if (aiProcessedCache?.objectUrl) URL.revokeObjectURL(aiProcessedCache.objectUrl);
  const objectUrl = URL.createObjectURL(blob);
  const image = await loadImage(objectUrl);
  const alpha = getAlphaStats(image);
  if (alpha.coverage < MIN_AI_ALPHA_COVERAGE || alpha.opaquePixels < MIN_AI_OPAQUE_PIXELS) {
    URL.revokeObjectURL(objectUrl);
    if (status) {
      status.style.display = 'block';
      status.style.color = 'var(--danger-color)';
      status.textContent = 'AI isolation returned an empty mask; using the original image.';
    }
    throw new Error('AI isolation returned an empty mask');
  }
  aiProcessedCache = { sourceKey: key, mode, blob, objectUrl, image };
  if (status) { status.textContent = 'Cached ✓'; status.style.color = ''; }
  return image;
}

function getAlphaStats(image) {
  const canvas = document.createElement('canvas');
  canvas.width = image.naturalWidth || image.width;
  canvas.height = image.naturalHeight || image.height;
  const ctx = canvas.getContext('2d');
  ctx.drawImage(image, 0, 0);
  const data = ctx.getImageData(0, 0, canvas.width, canvas.height).data;
  let opaquePixels = 0;
  for (let i = 3; i < data.length; i += 4) {
    if (data[i] > 10) opaquePixels++;
  }
  return {
    opaquePixels,
    coverage: opaquePixels / (canvas.width * canvas.height),
  };
}

function _currentAIMode() {
  const sel = document.getElementById('select-ai-isolation');
  const mode = sel ? sel.value : 'off';
  return mode === 'clothing-isolate' ? 'off' : mode;
}

function _chromaKeyEnabled() {
  const c = document.getElementById('chk-chromakey');
  return !!(c && c.checked);
}

function _subtractEnabled() {
  const c = document.getElementById('chk-subtract-body');
  return !!(c && c.checked);
}

function updatePreviewPipelineStatus(busy = false) {
  const status = document.getElementById('preview-pipeline-status');
  if (!status) return;

  status.textContent = '';

  const title = document.createElement('span');
  title.className = 'preview-pipeline-title';
  title.textContent = busy ? 'Rendering' : 'Preview';
  status.appendChild(title);

  const aiMode = _currentAIMode();
  const steps = [
    { label: pendingAssetImage ? 'Source' : 'No image', active: !!pendingAssetImage },
    { label: aiMode === 'off' ? 'AI off' : 'AI', active: aiMode !== 'off' },
    { label: 'Key', active: _chromaKeyEnabled() },
    { label: 'Subtract', active: _subtractEnabled() },
  ];

  if (busy) {
    steps.push({ label: 'Updating', active: true, busy: true });
  }

  for (const step of steps) {
    const chip = document.createElement('span');
    chip.className = `preview-chip${step.active ? ' active' : ''}${step.busy ? ' busy' : ''}`;
    chip.textContent = step.label;
    status.appendChild(chip);
  }
}

async function applyBodySubtractionToCanvas(canvas) {
  const origCtx = canvas.getContext('2d');
  const refCanvas = await generateDynamicBodyReferenceCanvas();

  const scaledRefCanvas = document.createElement('canvas');
  scaledRefCanvas.width = canvas.width;
  scaledRefCanvas.height = canvas.height;
  const scaledRefCtx = scaledRefCanvas.getContext('2d');
  scaledRefCtx.drawImage(refCanvas, 0, 0, canvas.width, canvas.height);

  const origData = origCtx.getImageData(0, 0, canvas.width, canvas.height);
  const pixels = origData.data;
  const refData = scaledRefCtx.getImageData(0, 0, scaledRefCanvas.width, scaledRefCanvas.height).data;

  const width = canvas.width;
  const height = canvas.height;
  const dist = new Int32Array(width * height);
  const nearestIdx = new Int32Array(width * height);
  const maxDist = 999999;

  for (let i = 0; i < width * height; i++) {
    if (refData[i * 4 + 3] > 10) { dist[i] = 0; nearestIdx[i] = i; }
    else { dist[i] = maxDist; nearestIdx[i] = -1; }
  }

  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      const idx = y * width + x;
      if (dist[idx] > 0) {
        let d = dist[idx], n = nearestIdx[idx];
        if (x > 0 && dist[idx - 1] + 1 < d) { d = dist[idx - 1] + 1; n = nearestIdx[idx - 1]; }
        if (y > 0 && dist[idx - width] + 1 < d) { d = dist[idx - width] + 1; n = nearestIdx[idx - width]; }
        dist[idx] = d; nearestIdx[idx] = n;
      }
    }
  }

  for (let y = height - 1; y >= 0; y--) {
    for (let x = width - 1; x >= 0; x--) {
      const idx = y * width + x;
      if (dist[idx] > 0) {
        let d = dist[idx], n = nearestIdx[idx];
        if (x < width - 1 && dist[idx + 1] + 1 < d) { d = dist[idx + 1] + 1; n = nearestIdx[idx + 1]; }
        if (y < height - 1 && dist[idx + width] + 1 < d) { d = dist[idx + width] + 1; n = nearestIdx[idx + width]; }
        dist[idx] = d; nearestIdx[idx] = n;
      }
    }
  }

  const tol = parseInt(document.getElementById('range-subtract-tolerance')?.value || '60', 10);
  const maxSearchRadius = 15;

  for (let i = 0; i < pixels.length; i += 4) {
    const a = pixels[i + 3];
    if (a > 0) {
      const pixelIdx = i / 4;
      const d = dist[pixelIdx];
      if (d <= maxSearchRadius) {
        const nIdx = nearestIdx[pixelIdx];
        if (nIdx >= 0) {
          const diff = Math.abs(pixels[i] - refData[nIdx * 4]) +
                       Math.abs(pixels[i + 1] - refData[nIdx * 4 + 1]) +
                       Math.abs(pixels[i + 2] - refData[nIdx * 4 + 2]);
          if (diff < tol) pixels[i + 3] = 0;
        }
      }
    }
  }

  origCtx.putImageData(origData, 0, 0);
}

function cleanupHasEdits() {
  return cleanupState.operations.length > 0 || cleanupState.manualEdits > 0;
}

function getCleanupMetadata() {
  if (!cleanupState.initialized) return null;
  return {
    source_lane: cleanupState.sourceLane,
    operations: [...cleanupState.operations],
    manual_edits: cleanupState.manualEdits,
  };
}

function canvasImageData(canvas) {
  return canvas.getContext('2d').getImageData(0, 0, canvas.width, canvas.height);
}

function putCanvasImageData(canvas, imageData) {
  const ctx = canvas.getContext('2d');
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.putImageData(imageData, 0, 0);
}

function cleanupControls() {
  return {
    lane: document.getElementById('select-cleanup-lane'),
    whiteBg: document.getElementById('chk-cleanup-white-bg'),
    colorKey: document.getElementById('chk-cleanup-color-key'),
    keyColor: document.getElementById('color-cleanup-key'),
    keyTol: document.getElementById('range-cleanup-key-tolerance'),
    alpha: document.getElementById('range-cleanup-alpha-threshold'),
    halo: document.getElementById('chk-cleanup-halo'),
    largest: document.getElementById('chk-cleanup-largest'),
    islands: document.getElementById('chk-cleanup-islands'),
    islandSize: document.getElementById('range-cleanup-island-size'),
    bodySubtract: document.getElementById('chk-cleanup-body-subtract'),
    allowedOverlay: document.getElementById('chk-cleanup-allowed-overlay'),
    forbiddenOverlay: document.getElementById('chk-cleanup-forbidden-overlay'),
    brush: document.getElementById('range-cleanup-brush'),
    zoom: document.getElementById('range-cleanup-zoom'),
    zoomFit: document.getElementById('btn-cleanup-fit'),
    eraser: document.getElementById('btn-cleanup-eraser'),
    restore: document.getElementById('btn-cleanup-restore'),
    undo: document.getElementById('btn-cleanup-undo'),
    reset: document.getElementById('btn-cleanup-reset'),
  };
}

function syncCleanupControlLabels() {
  const c = cleanupControls();
  const keyTol = document.getElementById('val-cleanup-key-tolerance');
  const alpha = document.getElementById('val-cleanup-alpha-threshold');
  const island = document.getElementById('val-cleanup-island-size');
  const brush = document.getElementById('val-cleanup-brush');
  const zoom = document.getElementById('val-cleanup-zoom');
  if (keyTol && c.keyTol) keyTol.textContent = c.keyTol.value;
  if (alpha && c.alpha) alpha.textContent = c.alpha.value;
  if (island && c.islandSize) island.textContent = c.islandSize.value;
  if (brush && c.brush) brush.textContent = c.brush.value;
  if (zoom && c.zoom) zoom.textContent = c.zoom.value;
}

function applyCleanupZoom() {
  const canvas = document.getElementById('cleanup-candidate-canvas');
  const zoom = cleanupControls().zoom;
  if (!canvas || !zoom) return;
  const scale = parseInt(zoom.value || '100', 10) / 100;
  canvas.style.width = `${Math.max(1, Math.round(canvas.width * scale))}px`;
  canvas.style.height = `${Math.max(1, Math.round(canvas.height * scale))}px`;
  syncCleanupControlLabels();
}

function fitCleanupZoom() {
  const frame = document.querySelector('.cleanup-edit-frame');
  const canvas = document.getElementById('cleanup-candidate-canvas');
  const zoom = cleanupControls().zoom;
  if (!frame || !canvas || !zoom) return;
  const fit = Math.floor(Math.min(frame.clientWidth / canvas.width, frame.clientHeight / canvas.height) * 100);
  zoom.value = String(Math.max(100, Math.min(800, fit || 100)));
  applyCleanupZoom();
}

async function initCleanupWorkbenchForImage(image) {
  const details = document.getElementById('details-cleanup-workbench');
  const sourceCanvas = document.getElementById('cleanup-source-canvas');
  const candidateCanvas = document.getElementById('cleanup-candidate-canvas');
  if (!sourceCanvas || !candidateCanvas) return;

  const w = image.naturalWidth || image.width;
  const h = image.naturalHeight || image.height;
  sourceCanvas.width = w;
  sourceCanvas.height = h;
  candidateCanvas.width = w;
  candidateCanvas.height = h;
  const sourceCtx = sourceCanvas.getContext('2d');
  sourceCtx.clearRect(0, 0, w, h);
  sourceCtx.drawImage(image, 0, 0, w, h);

  cleanupState.initialized = true;
  cleanupState.sourceCanvas = sourceCanvas;
  cleanupState.sourceImageData = canvasImageData(sourceCanvas);
  cleanupState.candidateCanvas = candidateCanvas;
  cleanupState.candidateImageData = cloneCleanupImageData(cleanupState.sourceImageData);
  cleanupState.manualMaskImageData = null;
  cleanupState.undoStack = [];
  cleanupState.manualEdits = 0;
  cleanupState.operations = [];
  cleanupState.sourceLane = cleanupControls().lane?.value || 'transparent_png';
  cleanupState.activeMaskCache = {};

  if (details) details.open = true;
  putCanvasImageData(candidateCanvas, cleanupState.candidateImageData);
  fitCleanupZoom();
  await applyCleanupFromControls({ preserveManual: false });
}

async function setPendingAssetFromCleanup() {
  if (!cleanupState.candidateCanvas || !cleanupState.candidateImageData) return;
  putCanvasImageData(cleanupState.candidateCanvas, cleanupState.candidateImageData);
  const blob = await canvasToBlob(cleanupState.candidateCanvas);
  const file = new File([blob], pendingAssetFile?.name || 'cleaned_asset.png', { type: 'image/png' });
  const url = URL.createObjectURL(blob);
  const image = await loadImage(url);
  setPendingAsset(file, image);
  setPendingPreviewImage(null);
  scheduleImportPreview();
}

async function applyCleanupFromControls({ preserveManual = true } = {}) {
  if (!cleanupState.sourceImageData || !cleanupState.candidateCanvas) return;
  const c = cleanupControls();
  syncCleanupControlLabels();

  const operations = [];
  let img = cloneCleanupImageData(cleanupState.sourceImageData);
  if (c.whiteBg?.checked) {
    img = removeWhiteBackground(img, parseInt(c.keyTol?.value || '40', 10));
    operations.push('remove_white_background');
  }
  if (c.colorKey?.checked) {
    img = removeColorKey(img, parseHexColor(c.keyColor?.value || '#ffffff'), parseInt(c.keyTol?.value || '40', 10));
    operations.push('color_key');
  }
  const alphaThreshold = parseInt(c.alpha?.value || '10', 10);
  if (alphaThreshold > 10) {
    img = applyAlphaThreshold(img, alphaThreshold);
    operations.push('alpha_threshold');
  }
  if (c.halo?.checked) {
    img = cleanupHalo(img);
    operations.push('halo_cleanup');
  }
  if (c.largest?.checked) {
    img = keepLargestConnectedComponent(img);
    operations.push('keep_largest_connected_component');
  }
  if (c.islands?.checked) {
    img = removeSmallIslands(img, parseInt(c.islandSize?.value || '32', 10));
    operations.push('remove_small_islands');
  }
  if (c.bodySubtract?.checked) {
    operations.push('body_subtraction_on_bake');
  }

  if (preserveManual && cleanupState.manualMaskImageData) {
    img = applyManualMask(img, cleanupState.manualMaskImageData);
  }

  cleanupState.sourceLane = c.lane?.value || 'transparent_png';
  cleanupState.operations = operations;
  cleanupState.candidateImageData = img;
  putCanvasImageData(cleanupState.candidateCanvas, img);
  syncWorkbenchBodySubtract();
  await setPendingAssetFromCleanup();
  await renderCleanupBodyPreview();
  await updateCleanupWarnings();
}

function applyManualMask(imageData, maskImageData) {
  const out = cloneCleanupImageData(imageData);
  for (let i = 0; i < out.data.length; i += 4) {
    const mode = maskImageData.data[i];
    if (mode === 1) {
      out.data[i + 3] = 0;
    } else if (mode === 2) {
      out.data[i] = cleanupState.sourceImageData.data[i];
      out.data[i + 1] = cleanupState.sourceImageData.data[i + 1];
      out.data[i + 2] = cleanupState.sourceImageData.data[i + 2];
      out.data[i + 3] = cleanupState.sourceImageData.data[i + 3];
    }
  }
  return out;
}

function syncWorkbenchBodySubtract() {
  const c = cleanupControls();
  const existing = document.getElementById('chk-subtract-body');
  if (existing && c.bodySubtract) {
    existing.checked = c.bodySubtract.checked;
    existing.dispatchEvent(new Event('change', { bubbles: true }));
  }
}

async function renderCleanupBodyPreview() {
  const preview = document.getElementById('cleanup-body-preview-canvas');
  if (!preview || !cleanupState.candidateCanvas) return;
  const docW = DOLL_CONFIG.canvas?.width || 768;
  const docH = DOLL_CONFIG.canvas?.height || 768;
  preview.width = docW;
  preview.height = docH;
  const ctx = preview.getContext('2d');
  ctx.clearRect(0, 0, docW, docH);
  try {
    const refCanvas = await generateDynamicBodyReferenceCanvas();
    ctx.globalAlpha = 0.42;
    ctx.drawImage(refCanvas, 0, 0, docW, docH);
    ctx.globalAlpha = 1;
  } catch (err) {
    console.warn('cleanup preview body reference failed:', err);
  }
  applyBakeTransform(ctx, cleanupState.candidateCanvas, docW, docH, alignSettings);
  await drawCleanupMaskOverlays(ctx, docW, docH);
}

function maskPathForCategory(category) {
  const cat = category === 'shoes' ? 'shoe' : category;
  return `base_rig/masks/${cat}_allowed_region.png`;
}

async function loadMaskCanvas(cacheKey, path, width, height) {
  const cached = cleanupState.activeMaskCache[cacheKey];
  if (cached && cached.width === width && cached.height === height) return cached;
  const img = await loadImage(path);
  const canvas = document.createElement('canvas');
  canvas.width = width;
  canvas.height = height;
  canvas.getContext('2d').drawImage(img, 0, 0, width, height);
  cleanupState.activeMaskCache[cacheKey] = canvas;
  return canvas;
}

async function drawCleanupMaskOverlays(ctx, docW, docH) {
  const c = cleanupControls();
  const slot = document.getElementById('select-ingest-slot')?.value || 'topwear';
  if (c.allowedOverlay?.checked) {
    try {
      const mask = await loadMaskCanvas(`allowed:${slot}`, maskPathForCategory(slot), docW, docH);
      tintMask(ctx, mask, 'rgba(46, 213, 115, 0.24)');
    } catch {}
  }
  if (c.forbiddenOverlay?.checked) {
    for (const name of ['face_forbidden_region', 'hair_forbidden_region']) {
      try {
        const mask = await loadMaskCanvas(`forbidden:${name}`, `base_rig/masks/${name}.png`, docW, docH);
        tintMask(ctx, mask, 'rgba(255, 71, 87, 0.28)');
      } catch {}
    }
  }
}

function tintMask(ctx, maskCanvas, color) {
  const tmp = document.createElement('canvas');
  tmp.width = maskCanvas.width;
  tmp.height = maskCanvas.height;
  const tctx = tmp.getContext('2d');
  tctx.fillStyle = color;
  tctx.fillRect(0, 0, tmp.width, tmp.height);
  tctx.globalCompositeOperation = 'destination-in';
  tctx.drawImage(maskCanvas, 0, 0);
  ctx.drawImage(tmp, 0, 0);
}

async function updateCleanupWarnings() {
  const el = document.getElementById('cleanup-warnings');
  if (!el || !cleanupState.candidateImageData) return;
  const warnings = [];
  const sourceStats = getCleanupAlphaStats(cleanupState.sourceImageData);
  const stats = getCleanupAlphaStats(cleanupState.candidateImageData);
  if (sourceStats.coverage > 0.98) warnings.push('Source appears to have no useful alpha channel.');
  if (stats.coverage < 0.002 || stats.opaquePixels < 128) warnings.push('Asset is nearly empty after cleanup.');
  if (stats.coverage > 0.92) warnings.push('Likely opaque background remains.');

  const docCanvas = document.createElement('canvas');
  const docW = DOLL_CONFIG.canvas?.width || 768;
  const docH = DOLL_CONFIG.canvas?.height || 768;
  docCanvas.width = docW;
  docCanvas.height = docH;
  applyBakeTransform(docCanvas.getContext('2d'), cleanupState.candidateCanvas, docW, docH, alignSettings);
  const docData = canvasImageData(docCanvas);
  const docStats = getCleanupAlphaStats(docData);
  const slot = document.getElementById('select-ingest-slot')?.value || 'topwear';
  if (docStats.bbox) {
    const ratio = (docStats.bbox.width * docStats.bbox.height) / (docW * docH);
    if (ratio < 0.01) warnings.push('Asset may be too small for the selected category.');
    if (ratio > 0.9) warnings.push('Asset may be too large for the selected category.');
  }

  try {
    const allowed = await loadMaskCanvas(`allowed:${slot}`, maskPathForCategory(slot), docW, docH);
    const allowedData = canvasImageData(allowed);
    const allowedOverlap = countVisibleMaskOverlap(docData, allowedData);
    if (allowedOverlap.visible > 0 && allowedOverlap.overlap / allowedOverlap.visible < 0.85) {
      warnings.push('Visible pixels likely extend outside the allowed region.');
    }
  } catch {}

  for (const name of ['face_forbidden_region', 'hair_forbidden_region']) {
    try {
      const forbidden = await loadMaskCanvas(`forbidden:${name}`, `base_rig/masks/${name}.png`, docW, docH);
      const forbiddenOverlap = countVisibleMaskOverlap(docData, canvasImageData(forbidden));
      if (forbiddenOverlap.overlap > 20) warnings.push('Visible pixels overlap a forbidden face/hair region.');
    } catch {}
  }

  if (warnings.length === 0) {
    el.style.display = 'none';
    el.textContent = '';
    return;
  }
  el.style.display = 'block';
  el.textContent = '';
  const ul = document.createElement('ul');
  for (const warning of warnings) {
    const li = document.createElement('li');
    li.textContent = warning;
    ul.appendChild(li);
  }
  el.appendChild(ul);
}

function canvasPointerCoords(canvas, e) {
  const rect = canvas.getBoundingClientRect();
  return {
    x: Math.round((e.clientX - rect.left) * canvas.width / rect.width),
    y: Math.round((e.clientY - rect.top) * canvas.height / rect.height),
  };
}

function applyCleanupBrushStroke(x, y) {
  if (!cleanupState.candidateImageData || !cleanupState.sourceImageData) return;
  if (!cleanupState.manualMaskImageData) {
    cleanupState.manualMaskImageData = new ImageData(cleanupState.candidateImageData.width, cleanupState.candidateImageData.height);
  }
  const c = cleanupControls();
  const radius = parseInt(c.brush?.value || '18', 10);
  const mode = cleanupState.brushTool === 'restore' ? 2 : 1;
  const { width, height } = cleanupState.candidateImageData;
  const r2 = radius * radius;
  for (let yy = Math.max(0, y - radius); yy <= Math.min(height - 1, y + radius); yy++) {
    for (let xx = Math.max(0, x - radius); xx <= Math.min(width - 1, x + radius); xx++) {
      const dx = xx - x;
      const dy = yy - y;
      if (dx * dx + dy * dy > r2) continue;
      const i = (yy * width + xx) * 4;
      cleanupState.manualMaskImageData.data[i] = mode;
      if (mode === 1) {
        cleanupState.candidateImageData.data[i + 3] = 0;
      } else {
        cleanupState.candidateImageData.data[i] = cleanupState.sourceImageData.data[i];
        cleanupState.candidateImageData.data[i + 1] = cleanupState.sourceImageData.data[i + 1];
        cleanupState.candidateImageData.data[i + 2] = cleanupState.sourceImageData.data[i + 2];
        cleanupState.candidateImageData.data[i + 3] = cleanupState.sourceImageData.data[i + 3];
      }
    }
  }
  putCanvasImageData(cleanupState.candidateCanvas, cleanupState.candidateImageData);
}

async function finishCleanupBrushStroke() {
  cleanupState.manualEdits++;
  await setPendingAssetFromCleanup();
  await renderCleanupBodyPreview();
  await updateCleanupWarnings();
}

function wireCleanupWorkbench() {
  const c = cleanupControls();
  const allControls = [
    c.lane, c.whiteBg, c.colorKey, c.keyColor, c.keyTol, c.alpha, c.halo,
    c.largest, c.islands, c.islandSize, c.bodySubtract, c.allowedOverlay,
    c.forbiddenOverlay,
  ].filter(Boolean);
  for (const control of allControls) {
    control.addEventListener('input', () => applyCleanupFromControls());
    control.addEventListener('change', () => applyCleanupFromControls());
  }

  if (c.lane) {
    c.lane.addEventListener('change', () => {
      const lane = c.lane.value;
      if (lane === 'white_background' && c.whiteBg) c.whiteBg.checked = true;
      if (lane === 'clothed_guide') {
        if (c.bodySubtract) c.bodySubtract.checked = true;
        if (c.allowedOverlay) c.allowedOverlay.checked = true;
        if (c.forbiddenOverlay) c.forbiddenOverlay.checked = true;
      }
      applyCleanupFromControls({ preserveManual: false });
    });
  }

  if (c.brush) {
    c.brush.addEventListener('input', syncCleanupControlLabels);
  }
  if (c.zoom) {
    c.zoom.addEventListener('input', applyCleanupZoom);
  }
  if (c.zoomFit) {
    c.zoomFit.addEventListener('click', fitCleanupZoom);
  }
  if (c.eraser) {
    c.eraser.addEventListener('click', () => {
      cleanupState.brushTool = 'erase';
      c.eraser.classList.add('active');
      c.restore?.classList.remove('active');
    });
  }
  if (c.restore) {
    c.restore.addEventListener('click', () => {
      cleanupState.brushTool = 'restore';
      c.restore.classList.add('active');
      c.eraser?.classList.remove('active');
    });
  }
  if (c.undo) {
    c.undo.addEventListener('click', async () => {
      const snap = cleanupState.undoStack.pop();
      if (!snap) return;
      cleanupState.candidateImageData = snap.candidate;
      cleanupState.manualMaskImageData = snap.manualMask;
      cleanupState.manualEdits = Math.max(0, cleanupState.manualEdits - 1);
      putCanvasImageData(cleanupState.candidateCanvas, cleanupState.candidateImageData);
      await setPendingAssetFromCleanup();
      await renderCleanupBodyPreview();
      await updateCleanupWarnings();
    });
  }
  if (c.reset) {
    c.reset.addEventListener('click', () => {
      cleanupState.manualMaskImageData = null;
      cleanupState.manualEdits = 0;
      cleanupState.undoStack = [];
      applyCleanupFromControls({ preserveManual: false });
    });
  }

  const candidateCanvas = document.getElementById('cleanup-candidate-canvas');
  if (candidateCanvas) {
    candidateCanvas.addEventListener('mousedown', (e) => {
      if (!cleanupState.candidateImageData) return;
      cleanupState.brushDown = true;
      cleanupState.undoStack.push({
        candidate: cloneCleanupImageData(cleanupState.candidateImageData),
        manualMask: cleanupState.manualMaskImageData ? cloneCleanupImageData(cleanupState.manualMaskImageData) : null,
      });
      const p = canvasPointerCoords(candidateCanvas, e);
      applyCleanupBrushStroke(p.x, p.y);
      e.preventDefault();
    });
    candidateCanvas.addEventListener('mousemove', (e) => {
      if (!cleanupState.brushDown) return;
      const p = canvasPointerCoords(candidateCanvas, e);
      applyCleanupBrushStroke(p.x, p.y);
      e.preventDefault();
    });
    window.addEventListener('mouseup', () => {
      if (!cleanupState.brushDown) return;
      cleanupState.brushDown = false;
      finishCleanupBrushStroke();
    });
  }
  syncCleanupControlLabels();
}

// Compose AI-cached or raw source. Chroma-only previews stay as source-space
// drawables; body subtraction is a canvas-space operation, so that preview is
// pre-baked and marked to bypass a second alignment transform in renderDoll.
async function _composePreviewSource() {
  if (!pendingAssetImage) return null;
  const docW = DOLL_CONFIG.canvas?.width || 768;
  const docH = DOLL_CONFIG.canvas?.height || 768;

  const aiMode = _currentAIMode();
  let source = pendingAssetImage;
  if (aiMode !== 'off') {
    try {
      const aiImg = await ensureAIProcessed(aiMode);
      if (aiImg) source = aiImg;
    } catch (e) {
      console.warn('ai-process failed, using raw source:', e);
    }
  }

  if (_subtractEnabled()) {
    const bakedCanvas = document.createElement('canvas');
    bakedCanvas.width = docW;
    bakedCanvas.height = docH;
    const bakedCtx = bakedCanvas.getContext('2d');
    applyBakeTransform(bakedCtx, source, docW, docH, alignSettings);
    if (_chromaKeyEnabled()) {
      const keyColor = document.getElementById('color-chromakey')?.value || '#ffffff';
      const tolerance = parseInt(document.getElementById('range-chromakey')?.value || '40', 10);
      applyChromaKey(bakedCanvas, keyColor, tolerance);
    }
    await applyBodySubtractionToCanvas(bakedCanvas);
    return { image: bakedCanvas, baked: true };
  }

  // Apply chroma key on top of whatever source we have (raw or AI-cleaned).
  // The overlay's applyBakeTransform handles the alignSettings positioning,
  // so here we work at the source's native pixel dimensions.
  if (_chromaKeyEnabled()) {
    const canvas = document.createElement('canvas');
    canvas.width = source.naturalWidth || source.width;
    canvas.height = source.naturalHeight || source.height;
    const ctx = canvas.getContext('2d');
    ctx.drawImage(source, 0, 0);
    const keyColor = document.getElementById('color-chromakey')?.value || '#ffffff';
    const tolerance = parseInt(document.getElementById('range-chromakey')?.value || '40', 10);
    applyChromaKey(canvas, keyColor, tolerance);
    source = canvas;
  }
  return { image: source, baked: false };
}

async function renderImportPreview() {
  if (!livePreviewTargetContainer) return;
  if (!pendingAssetImage) {
    setPendingPreviewImage(null);
    updatePreviewPipelineStatus(false);
    renderDoll(livePreviewTargetContainer);
    return;
  }
  try {
    updatePreviewPipelineStatus(true);
    const composed = await _composePreviewSource();
    setPendingPreviewImage(composed.image, { baked: composed.baked });
    updatePreviewPipelineStatus(false);
    renderDoll(livePreviewTargetContainer);
  } catch (e) {
    updatePreviewPipelineStatus(false);
    console.warn('preview render failed:', e);
  }
}

function scheduleImportPreview() {
  if (livePreviewRendering) {
    livePreviewDirty = true;
    return;
  }
  if (livePreviewScheduled) return;
  livePreviewScheduled = true;
  requestAnimationFrame(async () => {
    livePreviewScheduled = false;
    livePreviewRendering = true;
    try {
      await renderImportPreview();
    } finally {
      livePreviewRendering = false;
      if (livePreviewDirty) {
        livePreviewDirty = false;
        scheduleImportPreview();
      }
    }
  });
}

function _invalidateAICache() {
  if (aiProcessedCache?.objectUrl) URL.revokeObjectURL(aiProcessedCache.objectUrl);
  aiProcessedCache = null;
  const status = document.getElementById('ai-isolation-status');
  if (status) status.style.display = 'none';
  updatePreviewPipelineStatus(false);
}

export function initImport(targetContainer) {
  livePreviewTargetContainer = targetContainer;
  wirePSDImport(targetContainer);
  wireRigAutodetect();
  wireAssetIngest(targetContainer);
  wireMlBg(targetContainer);
  wireDragDrop(targetContainer);
  wireAlignment(targetContainer);
  wireAutoAlign(targetContainer);
  wireLivePreviewTriggers();
  wireCleanupWorkbench();
}

function wireLivePreviewTriggers() {
  const aiSelect = document.getElementById('select-ai-isolation');
  if (aiSelect) {
    aiSelect.addEventListener('change', () => {
      const status = document.getElementById('ai-isolation-status');
      if (status) status.style.display = 'none';
      updatePreviewPipelineStatus(false);
      scheduleImportPreview();
    });
  }
  const chromaToggle = document.getElementById('chk-chromakey');
  const chromaColor = document.getElementById('color-chromakey');
  const chromaTol = document.getElementById('range-chromakey');
  [chromaToggle, chromaColor, chromaTol].forEach(el => {
    if (el) el.addEventListener('input', scheduleImportPreview);
    if (el) el.addEventListener('change', scheduleImportPreview);
  });
  const subToggle = document.getElementById('chk-subtract-body');
  const subTol = document.getElementById('range-subtract-tolerance');
  [subToggle, subTol].forEach(el => {
    if (el) el.addEventListener('input', scheduleImportPreview);
    if (el) el.addEventListener('change', scheduleImportPreview);
  });
  updatePreviewPipelineStatus(false);
}

function wireRigAutodetect() {
  const dropZone = document.getElementById('rig-drop-zone');
  const input = document.getElementById('input-rig-silhouette');
  const status = document.getElementById('rig-autodetect-status');
  if (!dropZone || !input) return;

  function showStatus(html, color) {
    if (!status) return;
    status.style.display = 'block';
    status.style.color = color || '';
    status.innerHTML = html;
  }

  async function handle(file) {
    if (!file) return;
    showStatus(`<div class="spinner-container"><div class="spinner" style="width:14px;height:14px;border-width:1.5px;"></div><span>Analyzing ${file.name}…</span></div>`, '');
    try {
      const fd = new FormData();
      fd.append('image', file);
      const pose = document.getElementById('txt-rig-pose');
      const arch = document.getElementById('txt-rig-archetype');
      if (pose && pose.value.trim()) fd.append('pose', pose.value.trim());
      if (arch && arch.value.trim()) fd.append('body_archetype', arch.value.trim());

      const res = await fetch('/api/rig-autodetect', { method: 'POST', body: fd });
      if (!res.ok) {
        let detail = res.statusText;
        try { const j = await res.json(); detail = j.detail || detail; } catch {}
        throw new Error(`HTTP ${res.status}: ${detail}`);
      }
      const rig = await res.json();
      const count = Object.keys(rig.anchors || {}).length;

      const blob = new Blob([JSON.stringify(rig, null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = 'rig_auto.json';
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);

      const anchors = rig.anchors || {};
      const previewKeys = ['neck', 'left_shoulder', 'right_shoulder', 'hip_left', 'hip_right', 'ankle_left', 'ankle_right'];
      const lines = previewKeys.filter(k => anchors[k]).map(k => `  ${k}: [${anchors[k][0]}, ${anchors[k][1]}]`).join('\n');
      showStatus(`✓ Detected ${count} anchors. Downloaded <code>rig_auto.json</code>.<br><pre style="margin:0.4rem 0 0;font-size:0.65rem;line-height:1.3;">${lines}</pre><span style="font-size:0.65rem;color:var(--text-secondary)">Review and hand-adjust before replacing <code>base_rig/rig.json</code>.</span>`, 'var(--text-primary)');
    } catch (e) {
      console.error(e);
      showStatus(`✗ ${e.message}`, 'var(--danger-color)');
    }
  }

  dropZone.addEventListener('click', () => input.click());
  input.addEventListener('change', (e) => {
    if (e.target.files.length) handle(e.target.files[0]);
    e.target.value = '';
  });

  ['dragenter', 'dragover'].forEach(name =>
    dropZone.addEventListener(name, (e) => { e.preventDefault(); dropZone.classList.add('dragover'); }));
  ['dragleave', 'drop'].forEach(name =>
    dropZone.addEventListener(name, (e) => { e.preventDefault(); dropZone.classList.remove('dragover'); }));
  dropZone.addEventListener('drop', (e) => {
    const f = e.dataTransfer.files && e.dataTransfer.files[0];
    if (f && f.type.startsWith('image/')) handle(f);
  });
}

// ===== PSD Import =====

function wirePSDImport(targetContainer) {
  const psdDropZone = document.getElementById('psd-drop-zone');
  const inputPsd = document.getElementById('input-psd');

  if (psdDropZone) {
    psdDropZone.addEventListener('click', () => inputPsd.click());
    ['dragenter', 'dragover'].forEach(name => {
      psdDropZone.addEventListener(name, () => psdDropZone.classList.add('dragover'));
    });
    ['dragleave', 'drop'].forEach(name => {
      psdDropZone.addEventListener(name, () => psdDropZone.classList.remove('dragover'));
    });
    psdDropZone.addEventListener('drop', (e) => {
      if (e.dataTransfer.files.length > 0 && e.dataTransfer.files[0].name.endsWith('.psd')) {
        loadAndParsePSD(e.dataTransfer.files[0], targetContainer);
      }
    });
  }

  if (inputPsd) {
    inputPsd.addEventListener('change', (e) => {
      if (e.target.files.length > 0) {
        loadAndParsePSD(e.target.files[0], targetContainer);
      }
    });
  }
}

async function loadAndParsePSD(file, targetContainer) {
  const psdStatus = document.getElementById('psd-status');
  const txtPsdStatus = document.getElementById('txt-psd-status');
  const psdProgressBg = document.getElementById('psd-progress-bg');
  const psdProgressFill = document.getElementById('psd-progress-fill');

  psdStatus.style.display = 'block';
  txtPsdStatus.textContent = `Reading ${file.name}...`;
  psdProgressBg.style.display = 'block';
  psdProgressFill.style.width = '10%';

  const reader = new FileReader();
  reader.onload = async function(e) {
    try {
      psdProgressFill.style.width = '30%';
      txtPsdStatus.textContent = 'Parsing PSD layers...';

      const buffer = e.target.result;
      const psd = window.agPsd.readPsd(buffer);

      psdProgressFill.style.width = '55%';
      txtPsdStatus.textContent = 'Extracting layer canvases...';

      const rawLayers = [];
      function collectLayers(node) {
        if (node.children) {
          for (const child of node.children) {
            collectLayers(child);
          }
        } else if (node.canvas && node.canvas.width > 0 && node.canvas.height > 0) {
          rawLayers.push(node);
        }
      }

      if (psd.children) {
        for (const child of psd.children) {
          collectLayers(child);
        }
      }

      if (rawLayers.length === 0) {
        throw new Error('No valid layer images found in the PSD file.');
      }

      clearImageCache();

      const docWidth = psd.width || 768;
      const docHeight = psd.height || 768;

      const layersConfig = [];
      const wardrobeMapping = {};

      for (let idx = 0; idx < rawLayers.length; idx++) {
        const layer = rawLayers[idx];
        const cleanName = cleanLayerName(layer.name);
        const zIndex = (idx + 1) * 10;

        const fullCanvas = document.createElement('canvas');
        fullCanvas.width = docWidth;
        fullCanvas.height = docHeight;
        const ctx = fullCanvas.getContext('2d');
        ctx.drawImage(layer.canvas, layer.left, layer.top);

        const blob = await canvasToBlob(fullCanvas);
        const filename = `${cleanName}.png`;
        const objectUrl = URL.createObjectURL(blob);

        cacheImage(filename, objectUrl, blob);

        const category = getCategory(cleanName);
        const layerMeta = {
          id: cleanName,
          name: layer.name.trim(),
          file: filename,
          z: zIndex,
          category: category
        };

        if (category === 'wardrobe') {
          const slot = getWardrobeSlot(cleanName);
          const optVal = getOptionValue(cleanName, slot, file.name);
          layerMeta.subcategory = slot;
          layerMeta.optionValue = optVal;

          if (!wardrobeMapping[slot]) {
            wardrobeMapping[slot] = {
              name: slot.replace("wear", "wear").replace(/\b\w/g, c => c.toUpperCase()),
              layers: []
            };
          }
          wardrobeMapping[slot].layers.push({ id: cleanName, optionValue: optVal });
        } else if (category === 'hair') {
          const subcat = (cleanName.includes('front') || cleanName.includes('bang') || cleanName.includes('fringe')) ? 'hair_front' : 'hair_back';
          layerMeta.subcategory = subcat;
          layerMeta.toggleable = true;
          layerMeta.defaultVisible = true;
          layerMeta.dyeable = true;
        } else if (category === 'eyes') {
          let subcat = 'eyes_other';
          if (cleanName.includes('white')) subcat = 'eyewhite';
          else if (cleanName.includes('iris') || cleanName.includes('iride')) { subcat = 'irides'; layerMeta.dyeable = true; }
          else if (cleanName.includes('brow')) subcat = 'eyebrows';
          else if (cleanName.includes('lash')) subcat = 'eyelashes';
          layerMeta.subcategory = subcat;
          layerMeta.toggleable = true;
          layerMeta.defaultVisible = true;
        } else {
          let subcat = 'face';
          if (cleanName.includes('neck')) subcat = 'neck';
          else if (cleanName.includes('ears') || cleanName.includes('ear')) { subcat = 'ears'; layerMeta.toggleable = true; layerMeta.defaultVisible = true; }
          else if (cleanName.includes('nose')) { subcat = 'nose'; layerMeta.toggleable = true; layerMeta.defaultVisible = true; }
          else if (cleanName.includes('mouth')) { subcat = 'mouth'; layerMeta.toggleable = true; layerMeta.defaultVisible = true; }
          layerMeta.subcategory = subcat;
        }

        layersConfig.push(layerMeta);

        const percent = Math.floor(60 + (idx / rawLayers.length) * 35);
        psdProgressFill.style.width = `${percent}%`;
        txtPsdStatus.textContent = `Ingested layer ${idx + 1}/${rawLayers.length}: ${layer.name}`;
      }

      const wardrobeConfig = {};
      for (const [slot, slotData] of Object.entries(wardrobeMapping)) {
        const uniqueVals = [...new Set(slotData.layers.map(l => l.optionValue))];
        uniqueVals.sort((a, b) => {
          const sortKey = (v) => { if (v === 'skin_wear') return 0; if (v === 'clothing') return 1; return 2; };
          return sortKey(a) - sortKey(b);
        });

        const optionsList = [];
        for (const val of uniqueVals) {
          let display_name = val.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
          if (val === 'skin_wear') display_name = 'Naked / Skin Wear';
          else if (val === 'clothing') display_name = 'Cozy Clothing';

          const assoc_layers = slotData.layers.filter(l => l.optionValue === val).map(l => l.id);
          const skin_wear_layers = slotData.layers.filter(l => l.optionValue === 'skin_wear').map(l => l.id);
          let final_layers = [...assoc_layers];
          if (val !== 'skin_wear' && skin_wear_layers.length > 0) {
            final_layers = [...skin_wear_layers, ...assoc_layers];
          }

          optionsList.push({ value: val, name: display_name, layers: final_layers });
        }

        optionsList.push({ value: 'none', name: 'Invisible / None', layers: [] });

        const default_val = uniqueVals.includes('skin_wear') ? 'skin_wear' : (uniqueVals[0] || 'none');
        wardrobeConfig[slot] = {
          name: slot.replace("wear", "wear").replace(/\b\w/g, c => c.toUpperCase()),
          options: optionsList,
          defaultValue: default_val
        };
      }

      DOLL_CONFIG.canvas = { width: docWidth, height: docHeight };
      DOLL_CONFIG.layers = layersConfig;
      DOLL_CONFIG.wardrobe = wardrobeConfig;

      const dollContainer = document.getElementById('doll-container');
      if (dollContainer) {
        dollContainer.style.width = `${docWidth}px`;
        dollContainer.style.height = `${docHeight}px`;
      }
      const txtDimension = document.getElementById('txt-dimension');
      if (txtDimension) {
        txtDimension.textContent = `Canvas: ${docWidth} x ${docHeight} px`;
      }

      document.getElementById('txt-model-base').textContent = `Pipeline: Local PSD (${file.name})`;

      // Re-initialize everything (this also resets state.offsets so per-layer
      // pixel offsets from the prior rig don't carry over to a differently
      // sized canvas).
      const { initializeState } = await import('./state.js');
      initializeState();

      const { setCalibrationTabActive } = await import('./calibration.js');
      buildUI(targetContainer);
      buildCalibrateOptions();
      renderDoll(targetContainer);
      updateViewportTransform(document.getElementById('doll-container'));

      psdProgressFill.style.width = '100%';
      txtPsdStatus.textContent = `PSD ${file.name} successfully imported!`;
      setTimeout(() => {
        psdStatus.style.display = 'none';
        const detailsImport = document.getElementById('details-import-psd');
        if (detailsImport) detailsImport.removeAttribute('open');
      }, 2500);

    } catch (err) {
      console.error(err);
      txtPsdStatus.textContent = `Error parsing PSD: ${err.message}`;
      psdProgressFill.style.backgroundColor = 'var(--danger-color)';
    }
  };

  reader.readAsArrayBuffer(file);
}

// ===== Asset Ingestion =====

function wireAssetIngest(targetContainer) {
  const assetDropZone = document.getElementById('asset-drop-zone');
  const inputAsset = document.getElementById('input-asset');
  const assetDropText = document.getElementById('asset-drop-text');
  const txtIngestName = document.getElementById('txt-ingest-name');
  const btnIngestSubmit = document.getElementById('btn-ingest-submit');
  const selectIngestSlot = document.getElementById('select-ingest-slot');

  if (!assetDropZone) return;

  assetDropZone.addEventListener('click', () => inputAsset.click());
  inputAsset.addEventListener('change', (e) => {
    if (e.target.files.length > 0) handleAssetFileSelect(e.target.files[0], targetContainer);
  });

  ['dragenter', 'dragover'].forEach(name => {
    assetDropZone.addEventListener(name, () => assetDropZone.classList.add('dragover'));
  });
  ['dragleave', 'drop'].forEach(name => {
    assetDropZone.addEventListener(name, () => assetDropZone.classList.remove('dragover'));
  });
  assetDropZone.addEventListener('drop', (e) => {
    if (e.dataTransfer.files.length > 0 && e.dataTransfer.files[0].type.startsWith('image/')) {
      handleAssetFileSelect(e.dataTransfer.files[0], targetContainer);
    }
  });

  if (btnIngestSubmit) {
    btnIngestSubmit.addEventListener('click', () => processIngest(targetContainer, assetDropText, txtIngestName));
  }
}

async function handleAssetFileSelect(file, targetContainer) {
  clearFitPreview();
  _invalidateAICache();
  const assetDropText = document.getElementById('asset-drop-text');
  const txtIngestName = document.getElementById('txt-ingest-name');
  const btnIngestSubmit = document.getElementById('btn-ingest-submit');

  setPendingAsset(file, null);
  setPendingPreviewImage(null);
  assetDropText.innerHTML = `Selected: <strong>${file.name}</strong> <span class="browse-link" style="margin-left: 8px; font-weight: normal; font-size: 0.75rem;">(Change)</span>`;

  if (!txtIngestName.value) {
    const baseName = file.name.replace(/\.[^/.]+$/, "").replace(/_/g, ' ').replace(/-/g, ' ');
    txtIngestName.value = baseName.replace(/\b\w/g, c => c.toUpperCase());
  }

  btnIngestSubmit.removeAttribute('disabled');

  try {
    const fileUrl = URL.createObjectURL(file);
    const img = await loadImage(fileUrl);
    setPendingAsset(file, img);

    const docW = DOLL_CONFIG.canvas?.width || 768;
    const docH = DOLL_CONFIG.canvas?.height || 768;
    const fit = Math.min(1.0, docW / img.width, docH / img.height);
    alignSettings.x = 0;
    alignSettings.y = 0;
    alignSettings.scaleX = parseFloat(fit.toFixed(4));
    alignSettings.scaleY = parseFloat(fit.toFixed(4));

    const detailsAlign = document.getElementById('details-alignment');
    if (detailsAlign) detailsAlign.open = true;

    await initCleanupWorkbenchForImage(img);

    renderDoll(targetContainer);
    if (typeof updateAlignUI === 'function') updateAlignUI();
    scheduleImportPreview();
  } catch (e) {
    console.warn("Could not load garment image:", e);
  }
}

async function processIngest(targetContainer, assetDropText, txtIngestName) {
  if (!pendingAssetFile) {
    alert('Please select or drop an image asset first.');
    return;
  }

  const selectIngestSlot = document.getElementById('select-ingest-slot');
  const slot = selectIngestSlot.value;
  const btnIngestSubmit = document.getElementById('btn-ingest-submit');
  if (!btnIngestSubmit) return;

  clearFitPreview();

  const displayName = txtIngestName.value.trim() || 'Custom Option';
  const cleanName = `${slot}_${displayName.toLowerCase().replace(/\s+/g, '_').replace(/[^a-z0-9_]/g, '')}`;
  const filename = `${cleanName}.png`;
  const cleanupMetadata = getCleanupMetadata();
  const cleanupPreparedSource = cleanupHasEdits();

  btnIngestSubmit.setAttribute('disabled', 'true');
  btnIngestSubmit.textContent = 'Processing asset...';

  try {
    const docWidth = DOLL_CONFIG.canvas.width;
    const docHeight = DOLL_CONFIG.canvas.height;

    const origCanvas = document.createElement('canvas');
    origCanvas.width = docWidth;
    origCanvas.height = docHeight;
    const origCtx = origCanvas.getContext('2d');

    // If the user has an AI mode selected, use the cached AI-processed image
    // as the bake source instead of the raw file. This is the on-disk garment
    // PNG the wardrobe will keep.
    let originalImg;
    const aiMode = _currentAIMode();
    if (aiMode !== 'off') {
      try {
        originalImg = await ensureAIProcessed(aiMode);
      } catch (e) {
        console.warn('ai-process failed at bake, falling back to raw:', e);
      }
    }
    if (!originalImg) {
      const fileUrl = URL.createObjectURL(pendingAssetFile);
      originalImg = await loadImage(fileUrl);
    }

    applyBakeTransform(origCtx, originalImg, docWidth, docHeight, alignSettings);

    const chkChroma = document.getElementById('chk-chromakey');
    if (!cleanupPreparedSource && chkChroma && chkChroma.checked) {
      const keyColor = document.getElementById('color-chromakey').value;
      const tolerance = parseInt(document.getElementById('range-chromakey').value, 10);
      applyChromaKey(origCanvas, keyColor, tolerance);
    }

    const chkSubtract = document.getElementById('chk-subtract-body');
    if (chkSubtract && chkSubtract.checked) {
      try {
        await applyBodySubtractionToCanvas(origCanvas);
      } catch (refErr) {
        console.warn('Failed to subtract reference body:', refErr);
        alert('Could not generate dynamic body reference for clothing isolation. Proceeding without subtraction.');
      }
    }

    const finalBlob = await canvasToBlob(origCanvas);
    const finalObjectUrl = URL.createObjectURL(finalBlob);

    cacheImage(filename, finalObjectUrl, finalBlob);

    const CATEGORY_Z = {
      dress: 205, topwear: 210, outerwear: 215, bottomwear: 220,
      skirt: 225, pants: 225, legwear: 230, shoes: 235,
      handwear: 240, accessory: 245,
    };
    const newZ = CATEGORY_Z[slot] ?? 245;

    const newLayer = {
      id: cleanName,
      name: displayName,
      file: filename,
      z: newZ,
      category: 'wardrobe',
      subcategory: slot,
      optionValue: cleanName,
    };
    if (cleanupMetadata) {
      newLayer.cleanup = cleanupMetadata;
    }

    const existingLayerIndex = DOLL_CONFIG.layers.findIndex(l => l.id === cleanName);
    if (existingLayerIndex >= 0) {
      DOLL_CONFIG.layers[existingLayerIndex] = {
        ...DOLL_CONFIG.layers[existingLayerIndex],
        name: displayName,
        file: filename,
        ...(cleanupMetadata ? { cleanup: cleanupMetadata } : {}),
      };
    } else {
      DOLL_CONFIG.layers.push(newLayer);
    }

    const slotConfig = DOLL_CONFIG.wardrobe[slot];
    if (slotConfig) {
      const existingOptionIndex = slotConfig.options.findIndex(o => o.value === cleanName);
      const includeUnderwear = document.getElementById('chk-ingest-underwear');
      const layers = [];
      if (includeUnderwear && includeUnderwear.checked) {
        const skinWearOption = slotConfig.options.find(o => o.value === 'skin_wear');
        if (skinWearOption) layers.push(...skinWearOption.layers);
      }
      layers.push(cleanName);

      if (existingOptionIndex < 0) {
        slotConfig.options.push({ value: cleanName, name: displayName, layers: layers });
      } else {
        slotConfig.options[existingOptionIndex].name = displayName;
        slotConfig.options[existingOptionIndex].layers = layers;
      }
    }

    state.wardrobe[slot] = cleanName;

    setPendingPreviewImage(null);
    _invalidateAICache();

    buildUI(targetContainer);
    renderDoll(targetContainer);
    updateCalibrateUI();

    alert(`Successfully processed and added "${displayName}" to wardrobe!`);
  } catch (err) {
    console.error(err);
    alert(`Error ingesting asset: ${err.message}`);
  } finally {
    btnIngestSubmit.removeAttribute('disabled');
    btnIngestSubmit.textContent = 'Process & Add to Wardrobe';
  }
}

// ===== ML Background Removal =====

function wireMlBg(targetContainer) {
  const btnMlBg = document.getElementById('btn-ml-bg');
  if (!btnMlBg) return;

  btnMlBg.addEventListener('click', async () => {
    if (!pendingAssetFile) {
      alert('Please select or drop an image asset first.');
      return;
    }

    const mlStatus = document.getElementById('ml-status');
    const txtMlStatus = document.getElementById('txt-ml-status');
    mlStatus.style.display = 'block';
    txtMlStatus.textContent = 'Loading AI model (approx. 40MB)...';

    try {
      if (!mlBgModule) {
        mlBgModule = await import('https://cdn.jsdelivr.net/npm/@imgly/background-removal/+esm');
      }
      txtMlStatus.textContent = 'Removing background...';

      const processedBlob = await mlBgModule.removeBackground(pendingAssetFile);
      const newFile = new File([processedBlob], pendingAssetFile.name, { type: 'image/png' });
      setPendingAsset(newFile, null);

      const assetDropText = document.getElementById('asset-drop-text');
      assetDropText.innerHTML = `Processed with AI: <strong>${newFile.name}</strong> <span class="browse-link" style="margin-left: 8px; font-weight: normal; font-size: 0.75rem;">(Change)</span>`;

      const fileUrl = URL.createObjectURL(newFile);
      const img = await loadImage(fileUrl);
      setPendingAsset(newFile, img);
      renderDoll(targetContainer);

      txtMlStatus.textContent = 'Background removed successfully!';
      setTimeout(() => { mlStatus.style.display = 'none'; }, 1500);
    } catch (err) {
      console.error(err);
      txtMlStatus.textContent = `Error: ${err.message}`;
    }
  });
}

// ===== Drag & Drop =====

function wireDragDrop() {
  const dragDropOverlay = document.getElementById('drag-drop-overlay');
  if (!dragDropOverlay) return;

  function preventDefaults(e) { e.preventDefault(); e.stopPropagation(); }
  ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(name => {
    window.addEventListener(name, preventDefaults, false);
  });

  window.addEventListener('dragenter', (e) => {
    if (e.dataTransfer.types.includes('Files')) dragDropOverlay.classList.add('active');
  });
  window.addEventListener('dragover', (e) => {
    if (e.dataTransfer.types.includes('Files')) dragDropOverlay.classList.add('active');
  });
  dragDropOverlay.addEventListener('dragleave', () => dragDropOverlay.classList.remove('active'));
  dragDropOverlay.addEventListener('drop', (e) => {
    dragDropOverlay.classList.remove('active');
    const files = e.dataTransfer.files;
    if (files && files.length > 0) {
      const file = files[0];
      const targetContainer = document.getElementById('doll-layers-target');
      if (file.name.endsWith('.psd')) {
        switchToTab('studio');
        loadAndParsePSD(file, targetContainer);
      } else if (file.type.startsWith('image/')) {
        switchToTab('studio');
        handleAssetFileSelect(file, targetContainer);
      }
    }
  });
}

// ===== Visual Alignment =====

const rangeAlignX = document.getElementById('range-align-x');
const rangeAlignY = document.getElementById('range-align-y');
const rangeAlignScale = document.getElementById('range-align-scale');
const rangeAlignScaleX = document.getElementById('range-align-scale-x');
const rangeAlignScaleY = document.getElementById('range-align-scale-y');
const rangeAlignOpacity = document.getElementById('range-align-opacity');
const numAlignWidth = document.getElementById('num-align-width');
const numAlignHeight = document.getElementById('num-align-height');
const valAlignX = document.getElementById('val-align-x');
const valAlignY = document.getElementById('val-align-y');
const valAlignScale = document.getElementById('val-align-scale');
const valAlignScaleX = document.getElementById('val-align-scale-x');
const valAlignScaleY = document.getElementById('val-align-scale-y');
const valAlignOpacity = document.getElementById('val-align-opacity');

export function updateAlignUI() {
  if (rangeAlignX) rangeAlignX.value = alignSettings.x;
  if (rangeAlignY) rangeAlignY.value = alignSettings.y;
  if (rangeAlignScaleX) rangeAlignScaleX.value = alignSettings.scaleX;
  if (rangeAlignScaleY) rangeAlignScaleY.value = alignSettings.scaleY;
  if (rangeAlignOpacity) rangeAlignOpacity.value = alignSettings.opacity;

  if (valAlignX) valAlignX.textContent = alignSettings.x;
  if (valAlignY) valAlignY.textContent = alignSettings.y;
  if (valAlignScaleX) valAlignScaleX.textContent = alignSettings.scaleX.toFixed(2);
  if (valAlignScaleY) valAlignScaleY.textContent = alignSettings.scaleY.toFixed(2);
  if (valAlignOpacity) valAlignOpacity.textContent = alignSettings.opacity;

  // Uniform slider syncs only when X and Y are equal — otherwise we leave the
  // user's last uniform value alone so they don't lose it after a non-uniform edit.
  if (alignSettings.scaleX === alignSettings.scaleY) {
    if (rangeAlignScale) rangeAlignScale.value = alignSettings.scaleX;
    if (valAlignScale) valAlignScale.textContent = alignSettings.scaleX.toFixed(2);
  }

  if (pendingAssetImage) {
    if (numAlignWidth && document.activeElement !== numAlignWidth) {
      numAlignWidth.value = Math.round(pendingAssetImage.width * alignSettings.scaleX);
    }
    if (numAlignHeight && document.activeElement !== numAlignHeight) {
      numAlignHeight.value = Math.round(pendingAssetImage.height * alignSettings.scaleY);
    }
  }

  const overlay = document.querySelector('.pending-alignment-overlay');
  if (overlay && pendingAssetImage && overlay.getContext) {
    const ctx = overlay.getContext('2d');
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.clearRect(0, 0, overlay.width, overlay.height);
    // Honor the preview override if the importer has staged a masked source.
    const source = pendingPreviewImage || pendingAssetImage;
    if (pendingPreviewImage && pendingPreviewIsBaked) {
      ctx.drawImage(source, 0, 0, overlay.width, overlay.height);
      scheduleImportPreview();
    } else {
      applyBakeTransform(ctx, source, overlay.width, overlay.height, alignSettings);
    }
    overlay.style.opacity = alignSettings.opacity / 100;
  }
}

function wireAlignment(targetContainer) {
  if (rangeAlignX) {
    rangeAlignX.addEventListener('input', (e) => { alignSettings.x = parseInt(e.target.value, 10); updateAlignUI(); });
  }
  if (rangeAlignY) {
    rangeAlignY.addEventListener('input', (e) => { alignSettings.y = parseInt(e.target.value, 10); updateAlignUI(); });
  }
  if (rangeAlignScale) {
    rangeAlignScale.addEventListener('input', (e) => {
      const v = parseFloat(e.target.value);
      alignSettings.scaleX = v;
      alignSettings.scaleY = v;
      updateAlignUI();
    });
  }
  if (rangeAlignScaleX) {
    rangeAlignScaleX.addEventListener('input', (e) => { alignSettings.scaleX = parseFloat(e.target.value); updateAlignUI(); });
  }
  if (rangeAlignScaleY) {
    rangeAlignScaleY.addEventListener('input', (e) => { alignSettings.scaleY = parseFloat(e.target.value); updateAlignUI(); });
  }
  if (numAlignWidth) {
    numAlignWidth.addEventListener('input', (e) => {
      if (!pendingAssetImage) return;
      const px = parseInt(e.target.value, 10);
      if (isNaN(px)) return;
      const s = Math.max(0.05, Math.min(5.0, px / pendingAssetImage.width));
      alignSettings.scaleX = parseFloat(s.toFixed(4));
      updateAlignUI();
    });
  }
  if (numAlignHeight) {
    numAlignHeight.addEventListener('input', (e) => {
      if (!pendingAssetImage) return;
      const px = parseInt(e.target.value, 10);
      if (isNaN(px)) return;
      const s = Math.max(0.05, Math.min(5.0, px / pendingAssetImage.height));
      alignSettings.scaleY = parseFloat(s.toFixed(4));
      updateAlignUI();
    });
  }
  if (rangeAlignOpacity) {
    rangeAlignOpacity.addEventListener('input', (e) => {
      const prev = alignSettings.opacity;
      alignSettings.opacity = parseInt(e.target.value, 10);
      updateAlignUI();
      // renderDoll only when the overlay needs to appear/disappear; otherwise
      // updateAlignUI already updated the existing overlay's CSS opacity and
      // a full re-render would recreate the <img> and flicker the transform.
      if ((prev <= 0) !== (alignSettings.opacity <= 0)) {
        renderDoll(targetContainer);
      }
    });
  }

  const btnResetAlignment = document.getElementById('btn-reset-alignment');
  if (btnResetAlignment) {
    btnResetAlignment.addEventListener('click', () => {
      const docW = DOLL_CONFIG.canvas?.width || 768;
      const docH = DOLL_CONFIG.canvas?.height || 768;
      const fit = pendingAssetImage
        ? Math.min(1.0, docW / pendingAssetImage.width, docH / pendingAssetImage.height)
        : 1.0;
      alignSettings.x = 0;
      alignSettings.y = 0;
      alignSettings.scaleX = parseFloat(fit.toFixed(4));
      alignSettings.scaleY = parseFloat(fit.toFixed(4));
      alignSettings.opacity = 50;
      updateAlignUI();
      renderDoll(targetContainer);
    });
  }

  const dollContainer = document.getElementById('doll-container');
  if (!dollContainer) return;

  let isDraggingOverlay = false;
  let startX = 0, startY = 0, initialX = 0, initialY = 0;

  dollContainer.addEventListener('mousedown', (e) => {
    if (!pendingAssetImage || alignSettings.opacity <= 0) return;
    isDraggingOverlay = true;
    startX = e.clientX;
    startY = e.clientY;
    initialX = alignSettings.x;
    initialY = alignSettings.y;
    dollContainer.style.cursor = 'grabbing';
    e.preventDefault();
  });

  window.addEventListener('mousemove', (e) => {
    if (!isDraggingOverlay) return;
    const dx = e.clientX - startX;
    const dy = e.clientY - startY;
    const zoom = state.zoom || 1.0;
    alignSettings.x = Math.round(initialX + dx / zoom);
    alignSettings.y = Math.round(initialY + dy / zoom);
    updateAlignUI();
  });

  window.addEventListener('mouseup', () => {
    if (isDraggingOverlay) {
      isDraggingOverlay = false;
      updateDollCursor(dollContainer);
    }
  });

  dollContainer.addEventListener('wheel', (e) => {
    if (!pendingAssetImage || alignSettings.opacity <= 0) return;
    e.preventDefault();
    const factor = e.deltaY < 0 ? 1.02 : 1 / 1.02;
    const clamp = (v) => Math.max(0.05, Math.min(5.0, v * factor));
    alignSettings.scaleX = parseFloat(clamp(alignSettings.scaleX).toFixed(4));
    alignSettings.scaleY = parseFloat(clamp(alignSettings.scaleY).toFixed(4));
    updateAlignUI();
  }, { passive: false });

  window.addEventListener('keydown', (e) => {
    if (!pendingAssetImage) return;
    if (!['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight'].includes(e.key)) return;
    const active = document.activeElement;
    if (active && (active.tagName === 'INPUT' || active.tagName === 'TEXTAREA' || active.isContentEditable)) return;
    const step = e.shiftKey ? 10 : 1;
    if (e.key === 'ArrowUp') alignSettings.y -= step;
    else if (e.key === 'ArrowDown') alignSettings.y += step;
    else if (e.key === 'ArrowLeft') alignSettings.x -= step;
    else if (e.key === 'ArrowRight') alignSettings.x += step;
    e.preventDefault();
    updateAlignUI();
  });
}

// ===== Auto-Align =====

function wireAutoAlign(targetContainer) {
  const btnAutoAlign = document.getElementById('btn-auto-align');
  if (!btnAutoAlign) return;

  btnAutoAlign.addEventListener('click', async () => {
    if (!pendingAssetImage) {
      alert('Please select or drop an image asset first.');
      return;
    }

    btnAutoAlign.setAttribute('disabled', 'true');
    const origText = btnAutoAlign.textContent;
    btnAutoAlign.textContent = 'Calculating alignment...';

    try {
      const refCanvas = await generateDynamicBodyReferenceCanvas();
      const refBox = getBoundingBox(refCanvas);
      if (!refBox) {
        alert('Could not find character body reference contours. Make sure character layers are visible.');
        return;
      }

      const tempCanvas = document.createElement('canvas');
      tempCanvas.width = pendingAssetImage.width;
      tempCanvas.height = pendingAssetImage.height;
      const tempCtx = tempCanvas.getContext('2d');
      tempCtx.drawImage(pendingAssetImage, 0, 0);

      const chkChroma = document.getElementById('chk-chromakey');
      if (chkChroma && chkChroma.checked) {
        const keyColor = document.getElementById('color-chromakey').value;
        const tolerance = parseInt(document.getElementById('range-chromakey').value, 10);
        applyChromaKey(tempCanvas, keyColor, tolerance);
      }

      const uploadedBox = getBoundingBox(tempCanvas);
      if (!uploadedBox) {
        alert('Could not isolate clothing character bounds. Please check your chroma key background removal settings.');
        return;
      }

      const docW = DOLL_CONFIG.canvas?.width || 768;
      const docH = DOLL_CONFIG.canvas?.height || 768;

      const Sraw = Math.min(refBox.width / uploadedBox.width, refBox.height / uploadedBox.height);
      const S = parseFloat(Math.max(0.05, Math.min(5.0, Sraw)).toFixed(4));

      const sourceCenterX = uploadedBox.x + uploadedBox.width / 2;
      const sourceCenterY = uploadedBox.y + uploadedBox.height / 2;
      const refCenterX = refBox.x + refBox.width / 2;
      const refCenterY = refBox.y + refBox.height / 2;

      alignSettings.scaleX = S;
      alignSettings.scaleY = S;
      alignSettings.x = Math.round(refCenterX - docW / 2 - S * (sourceCenterX - pendingAssetImage.width / 2));
      alignSettings.y = Math.round(refCenterY - docH / 2 - S * (sourceCenterY - pendingAssetImage.height / 2));

      updateAlignUI();
      renderDoll(targetContainer);
    } catch (e) {
      console.error(e);
      alert('Error during auto-alignment: ' + e.message);
    } finally {
      btnAutoAlign.removeAttribute('disabled');
      btnAutoAlign.textContent = origText;
    }
  });
}

// Tab switching helper
function switchToTab(tabName) {
  document.querySelectorAll('.tab-btn').forEach(b => {
    b.classList.toggle('active', b.dataset.tab === tabName);
  });
  document.querySelectorAll('.tab-pane').forEach(p => {
    p.classList.toggle('active', p.id === `tab-${tabName}`);
  });
}
