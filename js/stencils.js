import { DOLL_CONFIG } from './state.js';
import { dilateMask, erodeMask, featherMask, keepLargestConnectedComponent } from './cleanup.js';
import { generateBodySilhouetteCanvas, generateBodyCompositeCanvas } from './export.js';
import { canvasToBlob, downloadBlob, getBoundingBox, loadImage } from './utils.js';
import { receiveAssetForCleanup } from './import.js';

const STORAGE_KEY = 'paperdoll_user_stencils_v1';
const IDB_NAME    = 'paperdoll_stencils';
const IDB_STORE   = 'stencils';
const IDB_VERSION = 1;

// ---------------------------------------------------------------------------
// IndexedDB persistence (replaces localStorage — no 5 MB quota)
// ---------------------------------------------------------------------------

let _idb = null;

function _openIDB() {
  if (_idb) return Promise.resolve(_idb);
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(IDB_NAME, IDB_VERSION);
    req.onupgradeneeded = e => {
      const db = e.target.result;
      if (!db.objectStoreNames.contains(IDB_STORE)) {
        db.createObjectStore(IDB_STORE, { keyPath: 'id' });
      }
    };
    req.onsuccess = e => { _idb = e.target.result; resolve(_idb); };
    req.onerror   = () => reject(req.error);
  });
}

async function _idbPut(record) {
  const db = await _openIDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(IDB_STORE, 'readwrite');
    tx.objectStore(IDB_STORE).put(record);
    tx.oncomplete = resolve;
    tx.onerror    = () => reject(tx.error);
  });
}

async function _idbDelete(id) {
  const db = await _openIDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(IDB_STORE, 'readwrite');
    tx.objectStore(IDB_STORE).delete(id);
    tx.oncomplete = resolve;
    tx.onerror    = () => reject(tx.error);
  });
}

async function _idbGetAll() {
  const db = await _openIDB();
  return new Promise((resolve, reject) => {
    const tx  = db.transaction(IDB_STORE, 'readonly');
    const req = tx.objectStore(IDB_STORE).getAll();
    req.onsuccess = () => resolve(req.result);
    req.onerror   = () => reject(req.error);
  });
}
const MASKS = [
  ['body_silhouette', 'Body silhouette'],
  ['character_composite', 'Character composite'],
  ['topwear_allowed_region', 'Topwear allowed'],
  ['top_allowed_region', 'Top allowed'],
  ['outerwear_allowed_region', 'Outerwear allowed'],
  ['dress_allowed_region', 'Dress allowed'],
  ['torso_region', 'Torso region'],
  ['leg_region', 'Leg region'],
  ['pants_allowed_region', 'Pants allowed'],
  ['skirt_allowed_region', 'Skirt allowed'],
  ['legwear_allowed_region', 'Legwear allowed'],
  ['shoe_allowed_region', 'Shoe allowed'],
  ['dress_region', 'Dress region'],
  ['shoe_region', 'Shoe region'],
  ['face_forbidden_region', 'Face protected'],
  ['hair_forbidden_region', 'Hair protected'],
];

const editor = {
  canvas: null,
  ctx: null,
  sourceCanvas: null,
  stencils: [],
  generatedVariants: [],
  selectedId: null,
  tool: 'paint',
  brush: 18,
  drawing: false,
  cropStart: null,
  cropEnd: null,
  undoStack: [],
};

function el(id) {
  return document.getElementById(id);
}

function docSize() {
  return {
    width: DOLL_CONFIG.canvas?.width || 768,
    height: DOLL_CONFIG.canvas?.height || 768,
  };
}

function maskPath(name) {
  return `base_rig/masks/${name}.png`;
}

function setStatus(message, isError = false) {
  const status = el('stencil-status');
  if (!status) return;
  status.style.display = message ? 'block' : 'none';
  status.style.color = isError ? 'var(--danger-color)' : '';
  status.textContent = message || '';
}

function setButtonState(id, active) {
  el(id)?.classList.toggle('active', !!active);
}

function canvasToDataUrl(canvas) {
  return canvas.toDataURL('image/png');
}

async function dataUrlToCanvas(dataUrl) {
  const image = await loadImage(dataUrl);
  const { width, height } = docSize();
  const canvas = document.createElement('canvas');
  canvas.width = width;
  canvas.height = height;
  canvas.getContext('2d').drawImage(image, 0, 0, width, height);
  return canvas;
}

function cloneCanvas(sourceCanvas) {
  const { width, height } = docSize();
  const canvas = document.createElement('canvas');
  canvas.width = width;
  canvas.height = height;
  canvas.getContext('2d').drawImage(sourceCanvas, 0, 0, width, height);
  return canvas;
}

function imageDataToCanvas(imageData) {
  const canvas = document.createElement('canvas');
  canvas.width = imageData.width;
  canvas.height = imageData.height;
  canvas.getContext('2d').putImageData(imageData, 0, 0);
  return canvas;
}

function canvasToImageData(canvas) {
  return canvas.getContext('2d', { willReadFrequently: true }).getImageData(0, 0, canvas.width, canvas.height);
}

function alphaMaskFromCanvas(canvas, threshold = 10) {
  const { width, height } = canvas;
  const src = canvasToImageData(canvas);
  const out = new Uint8ClampedArray(width * height * 4);
  for (let pixel = 0; pixel < width * height; pixel++) {
    const i = pixel * 4;
    const alpha = src.data[i + 3];
    const visible = alpha > threshold;
    out[i] = 255;
    out[i + 1] = 255;
    out[i + 2] = 255;
    out[i + 3] = visible ? 255 : 0;
  }
  return new ImageData(out, width, height);
}

function alphaMaskFromLumaCanvas(canvas, threshold = 24) {
  const { width, height } = canvas;
  const src = canvasToImageData(canvas);
  const out = new Uint8ClampedArray(width * height * 4);
  for (let pixel = 0; pixel < width * height; pixel++) {
    const i = pixel * 4;
    const value = Math.round((src.data[i] + src.data[i + 1] + src.data[i + 2]) / 3);
    const visible = value > threshold;
    out[i] = 255;
    out[i + 1] = 255;
    out[i + 2] = 255;
    out[i + 3] = visible ? 255 : 0;
  }
  return new ImageData(out, width, height);
}

function rectMaskFromBounds(bounds, width, height) {
  const out = new Uint8ClampedArray(width * height * 4);
  if (!bounds) return new ImageData(out, width, height);
  const left = Math.max(0, bounds.x);
  const top = Math.max(0, bounds.y);
  const right = Math.min(width, bounds.x + bounds.width);
  const bottom = Math.min(height, bounds.y + bounds.height);
  for (let y = top; y < bottom; y++) {
    for (let x = left; x < right; x++) {
      const i = (y * width + x) * 4;
      out[i] = 255;
      out[i + 1] = 255;
      out[i + 2] = 255;
      out[i + 3] = 255;
    }
  }
  return new ImageData(out, width, height);
}

function combineMasks(a, b, mode = 'intersect') {
  if (!a) return b;
  if (!b) return a;
  const width = a.width;
  const height = a.height;
  const out = new Uint8ClampedArray(width * height * 4);
  for (let pixel = 0; pixel < width * height; pixel++) {
    const i = pixel * 4;
    const av = a.data[i + 3] > 10;
    const bv = b.data[i + 3] > 10;
    const visible = mode === 'union' ? (av || bv) : (av && bv);
    out[i] = 255;
    out[i + 1] = 255;
    out[i + 2] = 255;
    out[i + 3] = visible ? 255 : 0;
  }
  return new ImageData(out, width, height);
}

function floodFillInteriorMask(barrierMask) {
  const width = barrierMask.width;
  const height = barrierMask.height;
  const barrier = barrierMask.data;
  const exterior = new Uint8Array(width * height);
  const queue = [];

  const enqueue = (idx) => {
    if (idx < 0 || idx >= width * height) return;
    if (exterior[idx]) return;
    if (barrier[idx * 4 + 3] > 10) return;
    exterior[idx] = 1;
    queue.push(idx);
  };

  for (let x = 0; x < width; x++) {
    enqueue(x);
    enqueue((height - 1) * width + x);
  }
  for (let y = 0; y < height; y++) {
    enqueue(y * width);
    enqueue(y * width + (width - 1));
  }

  for (let i = 0; i < queue.length; i++) {
    const idx = queue[i];
    const x = idx % width;
    const y = Math.floor(idx / width);
    enqueue(y * width + (x - 1));
    enqueue(y * width + (x + 1));
    enqueue((y - 1) * width + x);
    enqueue((y + 1) * width + x);
  }

  const out = new Uint8ClampedArray(width * height * 4);
  for (let pixel = 0; pixel < width * height; pixel++) {
    const i = pixel * 4;
    const inside = barrier[i + 3] <= 10 && !exterior[pixel];
    out[i] = 255;
    out[i + 1] = 255;
    out[i + 2] = 255;
    out[i + 3] = inside ? 255 : 0;
  }
  return new ImageData(out, width, height);
}

function lumaPercentileThreshold(canvas, percentile = 0.5, ignoreZeros = true) {
  const data = canvasToImageData(canvas).data;
  const values = [];
  for (let i = 0; i < data.length; i += 4) {
    const value = Math.round((data[i] + data[i + 1] + data[i + 2]) / 3);
    if (ignoreZeros && value <= 0) continue;
    values.push(value);
  }
  if (values.length === 0) return 0;
  values.sort((a, b) => a - b);
  const idx = Math.min(values.length - 1, Math.max(0, Math.round((values.length - 1) * percentile)));
  return values[idx];
}

function thresholdLumaMask(canvas, threshold, mode = 'above') {
  const imageData = canvasToImageData(canvas);
  const { width, height, data } = imageData;
  const out = new Uint8ClampedArray(width * height * 4);
  for (let pixel = 0; pixel < width * height; pixel++) {
    const i = pixel * 4;
    const value = Math.round((data[i] + data[i + 1] + data[i + 2]) / 3);
    const visible = mode === 'below' ? value <= threshold && value > 0 : value >= threshold;
    out[i] = 255;
    out[i + 1] = 255;
    out[i + 2] = 255;
    out[i + 3] = visible ? 255 : 0;
  }
  return new ImageData(out, width, height);
}

function maskToCanvas(mask) {
  return imageDataToCanvas(mask);
}

function canvasFromBase64(base64) {
  return loadImage(`data:image/png;base64,${base64}`).then(image => {
    const { width, height } = docSize();
    const canvas = document.createElement('canvas');
    canvas.width = width;
    canvas.height = height;
    canvas.getContext('2d').drawImage(image, 0, 0, width, height);
    return canvas;
  });
}

// IDB stores one record per stencil: { id, name, source, order, dataUrl }
// saveStencils is called fire-and-forget (no await at call sites).
function saveStencils() {
  _saveStencilsAsync().catch(err => console.warn('saveStencils failed:', err));
}

async function _saveStencilsAsync() {
  // Write/update every current stencil.
  const currentIds = new Set(editor.stencils.map(s => s.id));
  await Promise.all(editor.stencils.map((stencil, i) =>
    _idbPut({
      id:     stencil.id,
      name:   stencil.name,
      source: stencil.source,
      order:  i,
      dataUrl: canvasToDataUrl(stencil.canvas),
    })
  ));
  // Delete any IDB records that are no longer in editor.stencils.
  const all = await _idbGetAll();
  await Promise.all(
    all.filter(r => !currentIds.has(r.id)).map(r => _idbDelete(r.id))
  );
}

async function loadStoredStencils() {
  try {
    const records = await _idbGetAll();
    if (!records.length) {
      // One-time migration from localStorage if IDB is empty.
      const raw = localStorage.getItem(STORAGE_KEY);
      if (raw) {
        const stored = JSON.parse(raw);
        editor.stencils = [];
        for (const stencil of stored) {
          editor.stencils.push({
            id:     stencil.id,
            name:   stencil.name,
            source: stencil.source,
            canvas: await dataUrlToCanvas(stencil.dataUrl),
          });
        }
        editor.selectedId = editor.stencils[0]?.id || null;
        saveStencils(); // persist migrated data to IDB
        localStorage.removeItem(STORAGE_KEY);
      }
      return;
    }
    records.sort((a, b) => (a.order ?? 0) - (b.order ?? 0));
    editor.stencils = [];
    for (const r of records) {
      editor.stencils.push({
        id:     r.id,
        name:   r.name,
        source: r.source,
        canvas: await dataUrlToCanvas(r.dataUrl),
      });
    }
    editor.selectedId = editor.stencils[0]?.id || null;
  } catch (err) {
    console.warn('Could not load stored stencils:', err);
  }
}

function selectedStencil() {
  return editor.stencils.find(stencil => stencil.id === editor.selectedId) || null;
}

function syncSourceSelect() {
  const select = el('select-stencil-source');
  if (!select) return;
  select.textContent = '';
  for (const [value, label] of MASKS) {
    const option = document.createElement('option');
    option.value = value;
    option.textContent = label;
    select.appendChild(option);
  }
}

function syncUserSelect() {
  const select = el('select-user-stencil');
  const nameInput = el('txt-user-stencil-name');
  if (!select) return;
  select.textContent = '';
  if (editor.stencils.length === 0) {
    const option = document.createElement('option');
    option.value = '';
    option.textContent = 'No editable stencils';
    select.appendChild(option);
    if (nameInput) nameInput.value = 'Custom Stencil';
    syncFabricStencilSelects();
    return;
  }
  for (const stencil of editor.stencils) {
    const option = document.createElement('option');
    option.value = stencil.id;
    option.textContent = stencil.name;
    option.selected = stencil.id === editor.selectedId;
    select.appendChild(option);
  }
  const selected = selectedStencil();
  if (selected && nameInput) nameInput.value = selected.name;
  syncFabricStencilSelects();
}

function renderGallery() {
  const gallery = el('stencil-gallery');
  if (!gallery) return;
  gallery.textContent = '';
  const variants = editor.generatedVariants.length ? editor.generatedVariants : [];
  if (variants.length === 0) {
    const empty = document.createElement('div');
    empty.className = 'stencil-gallery-item';
    empty.style.cursor = 'default';
    empty.innerHTML = '<span>No generated variants yet</span>';
    gallery.appendChild(empty);
    return;
  }

  for (const variant of variants) {
    const item = document.createElement('button');
    item.type = 'button';
    item.className = `stencil-gallery-item${variant.id === editor.selectedId ? ' active' : ''}`;
    const thumb = document.createElement('canvas');
    thumb.width = 180;
    thumb.height = 180;
    const tctx = thumb.getContext('2d');
    const checker = 12;
    for (let y = 0; y < thumb.height; y += checker) {
      for (let x = 0; x < thumb.width; x += checker) {
        tctx.fillStyle = ((x / checker + y / checker) % 2) === 0 ? '#151b26' : '#1d2533';
        tctx.fillRect(x, y, checker, checker);
      }
    }
    tctx.drawImage(variant.canvas, 0, 0, thumb.width, thumb.height);
    const label = document.createElement('span');
    label.textContent = variant.name;
    item.appendChild(thumb);
    item.appendChild(label);
    item.addEventListener('click', () => {
      editor.selectedId = variant.id;
      syncUserSelect();
      drawEditor();
      renderGallery();
    });
    gallery.appendChild(item);
  }
}

async function loadMaskCanvas(maskName) {
  if (maskName === 'character_composite') {
    return cloneCanvas(await generateBodyCompositeCanvas());
  }
  const { width, height } = docSize();
  const image = await loadImage(maskPath(maskName));
  const canvas = document.createElement('canvas');
  canvas.width = width;
  canvas.height = height;
  canvas.getContext('2d').drawImage(image, 0, 0, width, height);
  return canvas;
}

function setTool(tool) {
  editor.tool = tool;
  for (const [id, value] of [
    ['btn-stencil-paint', 'paint'],
    ['btn-stencil-erase', 'erase'],
    ['btn-stencil-crop', 'crop'],
  ]) {
    el(id)?.classList.toggle('active', value === tool);
  }
}

function drawEditor() {
  if (!editor.ctx) return;
  const selected = selectedStencil();
  const source = selected?.canvas || editor.sourceCanvas;
  const ctx = editor.ctx;
  const canvas = editor.canvas;
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.fillStyle = '#10141d';
  ctx.fillRect(0, 0, canvas.width, canvas.height);

  if (!source) {
    ctx.fillStyle = '#8b95a7';
    ctx.font = '13px sans-serif';
    ctx.textAlign = 'center';
    ctx.fillText('Duplicate a source mask to edit it', canvas.width / 2, canvas.height / 2);
    return;
  }

  const checker = 16;
  for (let y = 0; y < canvas.height; y += checker) {
    for (let x = 0; x < canvas.width; x += checker) {
      ctx.fillStyle = ((x / checker + y / checker) % 2) === 0 ? '#151b26' : '#1d2533';
      ctx.fillRect(x, y, checker, checker);
    }
  }

  ctx.drawImage(source, 0, 0, canvas.width, canvas.height);

  if (editor.cropStart && editor.cropEnd) {
    const rect = cropRect();
    ctx.save();
    ctx.strokeStyle = '#ffdf5d';
    ctx.lineWidth = 2;
    ctx.setLineDash([6, 4]);
    ctx.strokeRect(rect.x, rect.y, rect.width, rect.height);
    ctx.restore();
  }
}

function pointFromEvent(event) {
  const rect = editor.canvas.getBoundingClientRect();
  return {
    x: ((event.clientX - rect.left) / rect.width) * editor.canvas.width,
    y: ((event.clientY - rect.top) / rect.height) * editor.canvas.height,
  };
}

function docPoint(point) {
  const { width, height } = docSize();
  return {
    x: Math.round((point.x / editor.canvas.width) * width),
    y: Math.round((point.y / editor.canvas.height) * height),
  };
}

function pushUndo() {
  const selected = selectedStencil();
  if (!selected) return;
  editor.undoStack.push(canvasToDataUrl(selected.canvas));
  if (editor.undoStack.length > 20) editor.undoStack.shift();
}

function paintAt(point) {
  const selected = selectedStencil();
  if (!selected) return;
  const p = docPoint(point);
  const radius = Math.max(1, Math.round(editor.brush));
  const ctx = selected.canvas.getContext('2d');
  ctx.save();
  ctx.globalCompositeOperation = editor.tool === 'erase' ? 'destination-out' : 'source-over';
  ctx.fillStyle = '#ffffff';
  ctx.beginPath();
  ctx.arc(p.x, p.y, radius, 0, Math.PI * 2);
  ctx.fill();
  ctx.restore();
  drawEditor();
}

function cropRect() {
  const a = editor.cropStart;
  const b = editor.cropEnd;
  const x = Math.min(a.x, b.x);
  const y = Math.min(a.y, b.y);
  return {
    x,
    y,
    width: Math.abs(a.x - b.x),
    height: Math.abs(a.y - b.y),
  };
}

function applyCrop() {
  const selected = selectedStencil();
  if (!selected || !editor.cropStart || !editor.cropEnd) return;
  const rect = cropRect();
  if (rect.width < 2 || rect.height < 2) return;
  pushUndo();
  const { width, height } = docSize();
  const sx = Math.round((rect.x / editor.canvas.width) * width);
  const sy = Math.round((rect.y / editor.canvas.height) * height);
  const sw = Math.round((rect.width / editor.canvas.width) * width);
  const sh = Math.round((rect.height / editor.canvas.height) * height);
  const tmp = document.createElement('canvas');
  tmp.width = width;
  tmp.height = height;
  tmp.getContext('2d').drawImage(selected.canvas, sx, sy, sw, sh, sx, sy, sw, sh);
  const ctx = selected.canvas.getContext('2d');
  ctx.clearRect(0, 0, width, height);
  ctx.drawImage(tmp, 0, 0);
  editor.cropStart = null;
  editor.cropEnd = null;
  saveStencils();
  drawEditor();
}

function canvasImageData(canvas) {
  return canvas.getContext('2d', { willReadFrequently: true }).getImageData(0, 0, canvas.width, canvas.height);
}

function putImageDataToCanvas(imageData, canvas) {
  canvas.getContext('2d').putImageData(imageData, 0, 0);
}

function selectedImageData() {
  const selected = selectedStencil();
  return selected ? canvasImageData(selected.canvas) : null;
}

function mutateSelectedWith(transform) {
  const imageData = selectedImageData();
  if (!imageData) return;
  replaceSelectedWithImageData(transform(imageData));
}

function replaceSelectedWithImageData(imageData) {
  const selected = selectedStencil();
  if (!selected || !imageData) return;
  pushUndo();
  putImageDataToCanvas(imageData, selected.canvas);
  saveStencils();
  drawEditor();
}

function invertSelected() {
  const data = selectedImageData();
  if (!data) return;
  for (let i = 0; i < data.data.length; i += 4) {
    const nextAlpha = data.data[i + 3] > 10 ? 0 : 255;
    data.data[i] = 255;
    data.data[i + 1] = 255;
    data.data[i + 2] = 255;
    data.data[i + 3] = nextAlpha;
  }
  replaceSelectedWithImageData(data);
}

async function duplicateSource() {
  const sourceName = el('select-stencil-source')?.value || 'body_silhouette';
  try {
    const canvas = await loadMaskCanvas(sourceName);
    const stencil = {
      id: `stencil_${Date.now()}_${Math.random().toString(16).slice(2)}`,
      name: `${sourceName}_copy`,
      source: sourceName,
      canvas,
    };
    editor.stencils.push(stencil);
    editor.selectedId = stencil.id;
    editor.undoStack = [];
    syncUserSelect();
    saveStencils();
    drawEditor();
    renderGallery();
    setStatus(`Editable stencil created from ${sourceName}.`);
  } catch (err) {
    setStatus(`Could not load ${sourceName}: ${err.message || err}`, true);
  }
}

async function exportCanvas(canvas, fallbackName) {
  if (!canvas) return;
  const blob = await new Promise(resolve => canvas.toBlob(resolve, 'image/png'));
  downloadBlob(blob, fallbackName);
}

async function exportSource() {
  const sourceName = el('select-stencil-source')?.value || 'body_silhouette';
  const canvas = await loadMaskCanvas(sourceName);
  await exportCanvas(canvas, `${sourceName}.png`);
}

async function exportEdit() {
  const selected = selectedStencil();
  if (!selected) return;
  await exportCanvas(selected.canvas, `${selected.name || 'custom_stencil'}.png`);
}

async function fetchReferenceChannels() {
  const silhouetteCanvas = await generateBodySilhouetteCanvas();
  const bodyCanvas = await generateBodyCompositeCanvas();
  const fd = new FormData();
  const silhouetteBlob = await canvasToBlob(silhouetteCanvas);
  const bodyBlob = await canvasToBlob(bodyCanvas);
  fd.append('image', new File([silhouetteBlob], 'body_silhouette.png', { type: 'image/png' }));
  fd.append('body', new File([bodyBlob], 'body_composite.png', { type: 'image/png' }));

  const res = await fetch('/api/reference-channels', { method: 'POST', body: fd });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const data = await res.json();
      detail = data.detail || detail;
    } catch {}
    throw new Error(`HTTP ${res.status}: ${detail}`);
  }
  return res.json();
}

async function buildGeometryVariants() {
  const sourceName = el('select-stencil-source')?.value || 'body_silhouette';
  if (sourceName === 'character_composite') {
    try {
      editor.sourceCanvas = await loadMaskCanvas(sourceName);
    } catch (err) {
      setStatus(`Could not refresh source: ${err.message || err}`, true);
      return;
    }
  }
  const source = editor.sourceCanvas;
  if (!source) {
    setStatus('No source mask available.', true);
    return;
  }

  const depthCutoff = Number(el('range-stencil-depth-cutoff')?.value || 58);
  const edgeGrow = Number(el('range-stencil-edge-grow')?.value || 8);

  setStatus('Building geometry variants...');
  try {
    const refs = await fetchReferenceChannels();
    const silhouetteCanvas = await canvasFromBase64(refs['silhouette.png']);
    const cannyCanvas = await canvasFromBase64(refs['canny.png']);
    const depthCanvas = await canvasFromBase64(refs['depth.png']);

    const sourceMask = alphaMaskFromCanvas(source);
    const silhouetteMask = alphaMaskFromCanvas(silhouetteCanvas);
    const silhouetteCrop = combineMasks(sourceMask, silhouetteMask, 'intersect');

    const bounds = getBoundingBox(silhouetteCanvas);
    const bboxMask = rectMaskFromBounds(bounds, silhouetteMask.width, silhouetteMask.height);
    const bboxCrop = combineMasks(sourceMask, bboxMask, 'intersect');

    const cannySeed = alphaMaskFromLumaCanvas(cannyCanvas, 20);
    const cannyBarrier = dilateMask(cannySeed, edgeGrow);
    const cannyRegion = floodFillInteriorMask(cannyBarrier);

    const depthPercentile = Math.min(0.95, Math.max(0.05, depthCutoff / 100));
    const depthThreshold = lumaPercentileThreshold(depthCanvas, depthPercentile, true);
    const depthNear = thresholdLumaMask(depthCanvas, depthThreshold, 'above');
    const depthFar = thresholdLumaMask(depthCanvas, depthThreshold, 'below');

    const cannyGeometry = combineMasks(cannyRegion, sourceMask, 'union');
    const depthGeometry = combineMasks(depthNear, sourceMask, 'union');
    const depthInverseGeometry = combineMasks(depthFar, sourceMask, 'union');
    const hybridGeometry = combineMasks(cannyRegion, depthNear, 'union');

    const created = [
      { name: `${sourceName}_silhouette_crop`, source: 'silhouette', canvas: imageDataToCanvas(silhouetteCrop) },
      { name: `${sourceName}_bbox_crop`, source: 'bbox', canvas: imageDataToCanvas(bboxCrop) },
      { name: `${sourceName}_canny_region`, source: 'canny_region', canvas: maskToCanvas(cannyRegion) },
      { name: `${sourceName}_depth_near`, source: 'depth_near', canvas: maskToCanvas(depthNear) },
      { name: `${sourceName}_depth_far`, source: 'depth_far', canvas: maskToCanvas(depthFar) },
      { name: `${sourceName}_canny_geometry`, source: 'canny_geometry', canvas: maskToCanvas(cannyGeometry) },
      { name: `${sourceName}_depth_geometry`, source: 'depth_geometry', canvas: maskToCanvas(depthGeometry) },
      { name: `${sourceName}_depth_inverse_geometry`, source: 'depth_inverse_geometry', canvas: maskToCanvas(depthInverseGeometry) },
      { name: `${sourceName}_hybrid_geometry`, source: 'hybrid_geometry', canvas: maskToCanvas(hybridGeometry) },
    ];

    for (const item of created) {
      editor.stencils.push({
        id: `stencil_${Date.now()}_${Math.random().toString(16).slice(2)}`,
        name: item.name,
        source: item.source,
        canvas: item.canvas,
      });
    }
    editor.generatedVariants = created.map((item, index) => ({
      id: editor.stencils[editor.stencils.length - created.length + index].id,
      name: item.name,
      canvas: item.canvas,
    }));
    editor.selectedId = editor.generatedVariants.at(-1)?.id || editor.selectedId;
    editor.undoStack = [];
    syncUserSelect();
    saveStencils();
    drawEditor();
    renderGallery();
    setStatus(`Created ${created.length} geometry variant masks from ${sourceName}. The canny/depth variants should now change with the slider.`);
  } catch (err) {
    setStatus(`Geometry build failed: ${err.message || err}`, true);
  }
}

async function undo() {
  const selected = selectedStencil();
  const snap = editor.undoStack.pop();
  if (!selected || !snap) return;
  selected.canvas = await dataUrlToCanvas(snap);
  saveStencils();
  drawEditor();
}

function deleteSelected() {
  const selected = selectedStencil();
  if (!selected) return;
  editor.stencils = editor.stencils.filter(stencil => stencil.id !== selected.id);
  editor.selectedId = editor.stencils[0]?.id || null;
  editor.undoStack = [];
  syncUserSelect();
  saveStencils();
  drawEditor();
  renderGallery();
}

function bindEvents() {
  el('select-stencil-source')?.addEventListener('change', async event => {
    try {
      editor.sourceCanvas = await loadMaskCanvas(event.target.value);
      drawEditor();
    } catch (err) {
      setStatus(err.message || String(err), true);
    }
  });
  el('select-user-stencil')?.addEventListener('change', event => {
    editor.selectedId = event.target.value;
    editor.undoStack = [];
    syncUserSelect();
    drawEditor();
    renderGallery();
  });
  el('txt-user-stencil-name')?.addEventListener('change', event => {
    const selected = selectedStencil();
    if (!selected) return;
    selected.name = event.target.value.trim() || 'Custom Stencil';
    syncUserSelect();
    saveStencils();
    renderGallery();
  });

  el('btn-stencil-duplicate')?.addEventListener('click', duplicateSource);
  el('btn-stencil-export-source')?.addEventListener('click', exportSource);
  el('btn-stencil-export-edit')?.addEventListener('click', exportEdit);
  el('btn-stencil-geometry')?.addEventListener('click', buildGeometryVariants);
  el('btn-stencil-paint')?.addEventListener('click', () => setTool('paint'));
  el('btn-stencil-erase')?.addEventListener('click', () => setTool('erase'));
  el('btn-stencil-crop')?.addEventListener('click', () => setTool('crop'));
  el('btn-stencil-apply-crop')?.addEventListener('click', applyCrop);
  el('btn-stencil-expand')?.addEventListener('click', () => mutateSelectedWith(imageData => dilateMask(imageData, 4)));
  el('btn-stencil-shrink')?.addEventListener('click', () => mutateSelectedWith(imageData => erodeMask(imageData, 4)));
  el('btn-stencil-feather')?.addEventListener('click', () => mutateSelectedWith(imageData => featherMask(imageData, 2)));
  el('btn-stencil-invert')?.addEventListener('click', invertSelected);
  el('btn-stencil-undo')?.addEventListener('click', undo);
  el('btn-stencil-delete')?.addEventListener('click', deleteSelected);
  el('range-stencil-brush')?.addEventListener('input', event => {
    editor.brush = parseInt(event.target.value, 10);
    el('val-stencil-brush').textContent = String(editor.brush);
  });
  el('range-stencil-depth-cutoff')?.addEventListener('input', event => {
    el('val-stencil-depth-cutoff').textContent = String(event.target.value);
  });
  el('range-stencil-edge-grow')?.addEventListener('input', event => {
    el('val-stencil-edge-grow').textContent = String(event.target.value);
  });

  el('btn-fabric-generate')?.addEventListener('click', buildFabricAsset);
  el('btn-fabric-download-composite')?.addEventListener('click', downloadFabricComposite);
  el('btn-fabric-download-manifest')?.addEventListener('click', downloadFabricManifest);
  el('select-fabric-wardrobe')?.addEventListener('change', () => {
    const sel = el('select-fabric-wardrobe');
    const item = _wardrobeManifest.find(m => m.asset_id === sel?.value);
    if (item?.category) {
      const labelEl = el('txt-fabric-label');
      if (labelEl) labelEl.value = item.category;
    }
  });
  el('range-fabric-warp-strength')?.addEventListener('input', e => {
    if (el('val-fabric-warp-strength')) el('val-fabric-warp-strength').textContent = e.target.value;
  });
  el('range-fabric-depth-sigma')?.addEventListener('input', e => {
    if (el('val-fabric-depth-sigma')) el('val-fabric-depth-sigma').textContent = e.target.value;
  });
  el('range-fabric-feather')?.addEventListener('input', e => {
    if (el('val-fabric-feather')) el('val-fabric-feather').textContent = e.target.value;
  });
  el('range-fabric-outline')?.addEventListener('input', e => {
    if (el('val-fabric-outline')) el('val-fabric-outline').textContent = e.target.value;
  });

  editor.canvas.addEventListener('mousedown', event => {
    const selected = selectedStencil();
    if (!selected) return;
    const point = pointFromEvent(event);
    editor.drawing = true;
    if (editor.tool === 'crop') {
      editor.cropStart = point;
      editor.cropEnd = point;
      drawEditor();
    } else {
      pushUndo();
      paintAt(point);
    }
    event.preventDefault();
  });
  editor.canvas.addEventListener('mousemove', event => {
    if (!editor.drawing) return;
    const point = pointFromEvent(event);
    if (editor.tool === 'crop') {
      editor.cropEnd = point;
      drawEditor();
    } else {
      paintAt(point);
    }
    event.preventDefault();
  });
  window.addEventListener('mouseup', () => {
    if (!editor.drawing) return;
    editor.drawing = false;
    if (editor.tool !== 'crop') saveStencils();
  });

  el('btn-tailor-generate')?.addEventListener('click', buildTailorAsset);
  el('btn-tailor-to-cleanup')?.addEventListener('click', _sendTailor);
  el('btn-tailor-to-bake')?.addEventListener('click', _sendTailor);
}

// ─── Digital Tailor ──────────────────────────────────────────────────────

let _tailorResult = null;

function initTailorSliderLabels() {
  const pairs = [
    ['range-tailor-expand-x', 'val-tailor-expand-x'],
    ['range-tailor-expand-y', 'val-tailor-expand-y'],
    ['range-tailor-dilate',   'val-tailor-dilate'],
    ['range-tailor-erode',    'val-tailor-erode'],
    ['range-tailor-smooth',   'val-tailor-smooth'],
    ['range-tailor-flare',    'val-tailor-flare'],
    ['range-tailor-taper',    'val-tailor-taper'],
  ];
  for (const [rangeId, valId] of pairs) {
    const range = el(rangeId);
    const span = el(valId);
    if (range && span) {
      range.addEventListener('input', () => { span.textContent = range.value; });
    }
  }
}

async function buildTailorAsset() {
  const statusEl = el('tailor-status');
  const resultEl = el('tailor-result');
  const setStatus = (msg, err = false) => {
    if (!statusEl) return;
    statusEl.style.display = 'block';
    statusEl.textContent = msg;
    statusEl.style.color = err ? 'var(--accent-red, #f44)' : 'var(--text-secondary)';
  };

  setStatus('Generating…');
  if (resultEl) resultEl.style.display = 'none';

  const fd = new FormData();
  fd.append('recipe', el('select-tailor-recipe')?.value || 'bodice');
  fd.append('color',  el('input-tailor-color')?.value || '#ffffff');
  fd.append('expand_x', el('range-tailor-expand-x')?.value || '0');
  fd.append('expand_y', el('range-tailor-expand-y')?.value || '0');
  fd.append('dilate_px', el('range-tailor-dilate')?.value || '0');
  fd.append('erode_px',  el('range-tailor-erode')?.value || '0');
  fd.append('smooth_px', el('range-tailor-smooth')?.value || '2');
  fd.append('flare_px',  el('range-tailor-flare')?.value || '0');
  fd.append('taper_px',  el('range-tailor-taper')?.value || '0');
  fd.append('edge_stroke', el('chk-tailor-edge-stroke')?.checked ? 'true' : 'false');
  fd.append('inner_shadow', el('chk-tailor-inner-shadow')?.checked ? 'true' : 'false');
  fd.append('highlight', el('chk-tailor-highlight')?.checked ? 'true' : 'false');

  const textureFile = el('input-tailor-texture')?.files?.[0];
  if (textureFile) fd.append('texture', textureFile);

  try {
    const res = await fetch('/api/construct-pattern', { method: 'POST', body: fd });
    const data = await res.json();
    if (!data.success) { setStatus(data.detail || 'Generation failed', true); return; }

    _tailorResult = data;
    const preview = el('tailor-preview-img');
    if (preview) preview.src = `data:image/png;base64,${data.image_b64}`;

    const meta = el('tailor-meta');
    if (meta) {
      const p = data.pattern;
      meta.textContent = `${p.recipe} · ${p.category} · ${p.area_px.toLocaleString()} px`;
    }

    setStatus('');
    if (statusEl) statusEl.style.display = 'none';
    if (resultEl) resultEl.style.display = 'block';
  } catch (err) {
    setStatus(`Error: ${err.message || err}`, true);
  }
}

async function _sendTailor() {
  if (!_tailorResult?.image_b64) return;
  const recipe = _tailorResult.pattern?.recipe || 'tailor';
  const b64 = _tailorResult.image_b64;
  const byteStr = atob(b64);
  const ab = new ArrayBuffer(byteStr.length);
  const view = new Uint8Array(ab);
  for (let i = 0; i < byteStr.length; i++) view[i] = byteStr.charCodeAt(i);
  const blob = new Blob([ab], { type: 'image/png' });
  await receiveAssetForCleanup(blob, `tailor_${recipe}.png`);
}

// ─── Fabric Asset Generator ───────────────────────────────────────────────

let _fabricResult = null;
let _wardrobeManifest = [];

async function loadFabricWardrobeSelect() {
  const sel = el('select-fabric-wardrobe');
  if (!sel) return;
  try {
    const res = await fetch('public/assets/wardrobe_manifest.json');
    _wardrobeManifest = await res.json();
  } catch {
    _wardrobeManifest = [];
  }
  sel.textContent = '';
  const blank = document.createElement('option');
  blank.value = '';
  blank.textContent = _wardrobeManifest.length ? '— pick a garment —' : '— no compiled assets found —';
  sel.appendChild(blank);
  for (const item of _wardrobeManifest) {
    const opt = document.createElement('option');
    opt.value = item.asset_id;
    opt.dataset.category = item.category || '';
    opt.dataset.path = `compiled/${item.category}/${item.asset_id}/clothing_front.png`;
    opt.textContent = item.display_name || item.asset_id;
    sel.appendChild(opt);
  }
}

function syncFabricStencilSelects() {
  const nearSel = el('select-fabric-near-stencil');
  if (!nearSel) return;
  nearSel.textContent = '';
  const none = document.createElement('option');
  none.value = '';
  none.textContent = '— none (use garment alpha) —';
  nearSel.appendChild(none);
  for (const stencil of editor.stencils) {
    const opt = document.createElement('option');
    opt.value = stencil.id;
    opt.textContent = stencil.name;
    nearSel.appendChild(opt);
  }
}

function setFabricStatus(msg, isError = false) {
  const status = el('fabric-pipeline-status');
  if (!status) return;
  status.style.display = msg ? 'block' : 'none';
  status.style.color = isError ? 'var(--danger-color)' : '';
  status.textContent = msg || '';
}

async function buildFabricAsset() {
  const wardrobeSel = el('select-fabric-wardrobe');
  const selectedAssetId = wardrobeSel?.value || '';
  const garmentFiles = el('input-fabric-garments')?.files;
  const nearId = el('select-fabric-near-stencil')?.value || '';
  const label = (el('txt-fabric-label')?.value || '').trim() || 'garment';

  if (!selectedAssetId && (!garmentFiles || garmentFiles.length === 0)) {
    setFabricStatus('Pick a garment from the wardrobe or upload a PNG.', true);
    return;
  }

  const warpStrength = Number(el('range-fabric-warp-strength')?.value ?? 35) / 100;
  const depthSigma = Number(el('range-fabric-depth-sigma')?.value ?? 40);
  const featherSize = Number(el('range-fabric-feather')?.value ?? 6);
  const outlineThickness = Number(el('range-fabric-outline')?.value ?? 1);

  const configOverride = {
    warp_strength: warpStrength,
    depth_blur_sigma: depthSigma,
    feather_size: featherSize,
    outline_thickness: outlineThickness,
    save_intermediates: false,
  };

  setFabricStatus('Running pipeline...');
  const btn = el('btn-fabric-generate');
  if (btn) btn.disabled = true;

  try {
    const fd = new FormData();

    // Primary: fetch from wardrobe; fallback: uploaded files
    if (selectedAssetId) {
      const item = _wardrobeManifest.find(m => m.asset_id === selectedAssetId);
      if (!item) throw new Error(`Wardrobe asset not found: ${selectedAssetId}`);
      const assetUrl = `public/assets/compiled/${item.category}/${item.asset_id}/clothing_front.png`;
      const garmentRes = await fetch(assetUrl);
      if (!garmentRes.ok) throw new Error(`Could not fetch garment: ${assetUrl}`);
      const blob = await garmentRes.blob();
      fd.append('garments', new File([blob], 'clothing_front.png', { type: 'image/png' }));
    } else {
      for (const file of garmentFiles) fd.append('garments', file);
    }

    // Optional stencil mask override
    if (nearId) {
      const nearStencil = editor.stencils.find(s => s.id === nearId);
      if (nearStencil) {
        const blob = await new Promise(resolve => nearStencil.canvas.toBlob(resolve, 'image/png'));
        fd.append('stencil_masks', new File([blob], `${nearStencil.name}.png`, { type: 'image/png' }));
      }
    }

    fd.append('label', label);
    fd.append('config_override', JSON.stringify(configOverride));

    const res = await fetch('/api/stencil-pipeline', { method: 'POST', body: fd });
    if (!res.ok) {
      let detail = res.statusText;
      try { const d = await res.json(); detail = d.detail || detail; } catch {}
      throw new Error(`HTTP ${res.status}: ${detail}`);
    }
    const data = await res.json();
    _fabricResult = data;

    const previews = el('fabric-result-previews');
    previews.textContent = '';

    const addPreview = (b64, lbl, semantic) => {
      const wrap = document.createElement('div');
      wrap.style.cssText = 'display:flex;flex-direction:column;align-items:center;gap:3px;';
      const img = document.createElement('img');
      img.src = `data:image/png;base64,${b64}`;
      img.style.cssText = 'width:120px;height:120px;object-fit:contain;border-radius:4px;background:#10141d;border:1px solid var(--border-glass);';
      const span = document.createElement('span');
      span.style.cssText = 'font-size:0.6rem;color:var(--text-secondary);max-width:120px;text-align:center;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;';
      span.textContent = lbl;
      wrap.appendChild(img);
      wrap.appendChild(span);

      if (semantic) {
        // Landmark count badge
        const lmCount = Object.keys(semantic.deepfashion2?.landmarks || {}).length;
        if (lmCount > 0) {
          const badge = document.createElement('span');
          badge.style.cssText = 'font-size:0.55rem;color:var(--text-secondary);background:rgba(255,255,255,0.07);border-radius:3px;padding:1px 4px;';
          badge.textContent = `${lmCount} landmarks`;
          wrap.appendChild(badge);
        }

        // Danbooru tag chips (neckline, sleeve, silhouette)
        const db = semantic.danbooru || {};
        const chips = [db.neckline_type, db.sleeve_length, db.silhouette].filter(t => t && t !== 'unknown');
        if (chips.length > 0) {
          const chipRow = document.createElement('div');
          chipRow.style.cssText = 'display:flex;flex-wrap:wrap;gap:2px;justify-content:center;max-width:120px;';
          for (const tag of chips) {
            const chip = document.createElement('span');
            chip.style.cssText = 'font-size:0.5rem;background:rgba(100,180,255,0.12);color:#7dbfff;border-radius:3px;padding:1px 4px;white-space:nowrap;';
            chip.textContent = tag.replace(/_/g, ' ');
            chipRow.appendChild(chip);
          }
          wrap.appendChild(chipRow);
        }

        // Face warning
        const faces = semantic.forbidden_regions?.faces || [];
        if (faces.length > 0) {
          const warn = document.createElement('span');
          warn.style.cssText = 'font-size:0.55rem;color:#ffb347;';
          warn.textContent = `⚠ ${faces.length} face region${faces.length > 1 ? 's' : ''}`;
          wrap.appendChild(warn);
        }
      }

      previews.appendChild(wrap);
    };

    if (data.composite_b64) addPreview(data.composite_b64, 'Composite', null);
    for (const layer of (data.layer_images || [])) {
      addPreview(layer.image_b64, layer.label, layer.semantic || null);
    }

    el('fabric-pipeline-result').style.display = 'block';
    setFabricStatus(`Done — asset ID: ${data.asset_id}`);
  } catch (err) {
    setFabricStatus(`Pipeline error: ${err.message || err}`, true);
  } finally {
    if (btn) btn.disabled = false;
  }
}

function downloadFabricComposite() {
  if (!_fabricResult?.composite_b64) return;
  const a = document.createElement('a');
  a.href = `data:image/png;base64,${_fabricResult.composite_b64}`;
  a.download = `${_fabricResult.asset_id || 'fabric_asset'}_composite.png`;
  a.click();
}

function downloadFabricManifest() {
  if (!_fabricResult?.manifest_entry) return;
  const blob = new Blob(
    [JSON.stringify(_fabricResult.manifest_entry, null, 2)],
    { type: 'application/json' },
  );
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = 'asset_manifest_entry.json';
  a.click();
  URL.revokeObjectURL(url);
}

export async function initStencils() {
  editor.canvas = el('stencil-editor-canvas');
  if (!editor.canvas) return;
  editor.ctx = editor.canvas.getContext('2d');
  syncSourceSelect();
  await loadStoredStencils();
  syncUserSelect();
  bindEvents();
  try {
    editor.sourceCanvas = await loadMaskCanvas(el('select-stencil-source')?.value || 'body_silhouette');
  } catch (err) {
    setStatus(`Stencil source unavailable: ${err.message || err}`, true);
  }
  setTool(editor.tool);
  if (el('val-stencil-brush')) el('val-stencil-brush').textContent = String(editor.brush);
  if (el('val-stencil-depth-cutoff')) el('val-stencil-depth-cutoff').textContent = el('range-stencil-depth-cutoff')?.value || '58';
  if (el('val-stencil-edge-grow')) el('val-stencil-edge-grow').textContent = el('range-stencil-edge-grow')?.value || '8';
  syncFabricStencilSelects();
  loadFabricWardrobeSelect();
  initTailorSliderLabels();
  drawEditor();
  renderGallery();

  window.addEventListener('paperdoll:psd-loaded', async () => {
    const sourceName = el('select-stencil-source')?.value || 'body_silhouette';
    if (sourceName === 'character_composite') {
      try {
        editor.sourceCanvas = await loadMaskCanvas(sourceName);
        drawEditor();
      } catch {}
    }
  });
}
