import { state, DOLL_CONFIG, TOGGLE_GROUPS, pushHistory } from './state.js';
import {
  renderDoll, pendingAssetFile, pendingAssetImage,
  setPendingAsset, clearImageCache, cacheImage, alignSettings,
  generateDynamicBodyReferenceCanvas, updateDollCursor, updateViewportTransform
} from './render.js';
import {
  cleanLayerName, getCategory, getWardrobeSlot, getOptionValue,
  canvasToBlob, loadImage, getBoundingBox, applyChromaKey,
  applyBakeTransform
} from './utils.js';
import { clearFitPreview } from './fit_preview.js';
import { buildUI, updateActiveOptionButton } from './wardrobe.js';
import { buildCalibrateOptions, updateCalibrateUI } from './calibration.js';

let mlBgModule = null;

export function initImport(targetContainer) {
  wirePSDImport(targetContainer);
  wireAssetIngest(targetContainer);
  wireMlBg(targetContainer);
  wireDragDrop(targetContainer);
  wireAlignment(targetContainer);
  wireAutoAlign(targetContainer);
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

      document.getElementById('txt-model-base').textContent = `Pipeline: Local PSD (${file.name})`;

      // Re-initialize everything
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
  const assetDropText = document.getElementById('asset-drop-text');
  const txtIngestName = document.getElementById('txt-ingest-name');
  const btnIngestSubmit = document.getElementById('btn-ingest-submit');

  setPendingAsset(file, null);
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

    renderDoll(targetContainer);
    if (typeof updateAlignUI === 'function') updateAlignUI();
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

  btnIngestSubmit.setAttribute('disabled', 'true');
  btnIngestSubmit.textContent = 'Processing asset...';

  try {
    const docWidth = DOLL_CONFIG.canvas.width;
    const docHeight = DOLL_CONFIG.canvas.height;

    const origCanvas = document.createElement('canvas');
    origCanvas.width = docWidth;
    origCanvas.height = docHeight;
    const origCtx = origCanvas.getContext('2d');

    const fileUrl = URL.createObjectURL(pendingAssetFile);
    const originalImg = await loadImage(fileUrl);

    applyBakeTransform(origCtx, originalImg, docWidth, docHeight, alignSettings);

    const chkChroma = document.getElementById('chk-chromakey');
    if (chkChroma && chkChroma.checked) {
      const keyColor = document.getElementById('color-chromakey').value;
      const tolerance = parseInt(document.getElementById('range-chromakey').value, 10);
      applyChromaKey(origCanvas, keyColor, tolerance);
    }

    const chkSubtract = document.getElementById('chk-subtract-body');
    if (chkSubtract && chkSubtract.checked) {
      try {
        const refCanvas = await generateDynamicBodyReferenceCanvas();

        const scaledRefCanvas = document.createElement('canvas');
        scaledRefCanvas.width = origCanvas.width;
        scaledRefCanvas.height = origCanvas.height;
        const scaledRefCtx = scaledRefCanvas.getContext('2d');
        scaledRefCtx.drawImage(refCanvas, 0, 0, origCanvas.width, origCanvas.height);

        const origData = origCtx.getImageData(0, 0, origCanvas.width, origCanvas.height);
        const pixels = origData.data;
        const refData = scaledRefCtx.getImageData(0, 0, scaledRefCanvas.width, scaledRefCanvas.height).data;

        const width = origCanvas.width;
        const height = origCanvas.height;
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

        const tol = parseInt(document.getElementById('range-subtract-tolerance').value, 10);
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

    const existingLayerIndex = DOLL_CONFIG.layers.findIndex(l => l.id === cleanName);
    if (existingLayerIndex >= 0) {
      DOLL_CONFIG.layers[existingLayerIndex] = { ...DOLL_CONFIG.layers[existingLayerIndex], name: displayName, file: filename };
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
    applyBakeTransform(ctx, pendingAssetImage, overlay.width, overlay.height, alignSettings);
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
