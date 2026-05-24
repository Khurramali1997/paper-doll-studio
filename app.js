import { loadProjectConfig, initializeState, state, DOLL_CONFIG, saveCustomization, loadCustomization, clearSavedCustomization, exportStateJSON, importStateJSON, pushHistory, undo, redo, canUndo, canRedo } from './js/state.js';
import { renderDoll, updateViewportTransform, updateDollCursor, pendingAssetImage, alignSettings } from './js/render.js';
import { buildUI, updateActiveOptionButton } from './js/wardrobe.js';
import { initCalibration, setCalibrationTabActive, buildCalibrateOptions, updateCalibrateUI } from './js/calibration.js';
import { initImport, updateAlignUI } from './js/import.js';
import { downloadConfig, downloadStateJSON, exportZIP, downloadBodySilhouette, downloadReferencePack } from './js/export.js';
import { initFitPreview, clearFitPreview } from './js/fit_preview.js';

// DOM refs
const targetContainer = document.getElementById('doll-layers-target');
const dollContainer = document.getElementById('doll-container');
const txtDimension = document.getElementById('txt-dimension');

// ===== App Initialization =====
async function init() {
  await loadProjectConfig();
  initializeState();
  loadAutoSavedState();

  setCanvasInfo();
  buildUI(targetContainer);
  buildCalibrateOptions();
  renderDoll(targetContainer);
  updateViewport();

  wireTabs();
  wireViewport();
  wireDesignOps(targetContainer);
  wireSaveLoad();
  wireUndoRedo(targetContainer);

  initCalibration(targetContainer);
  initImport(targetContainer);
  initFitPreview(targetContainer);

  // Chroma/subtract visibility toggle
  wireCheckboxVisibility();
}

function loadAutoSavedState() {
  const loaded = loadCustomization();
  if (loaded) console.log('Restored previous customization from localStorage');
}

function setCanvasInfo() {
  txtDimension.textContent = `Canvas: ${DOLL_CONFIG.canvas.width} x ${DOLL_CONFIG.canvas.height} px`;
  dollContainer.style.width = `${DOLL_CONFIG.canvas.width}px`;
  dollContainer.style.height = `${DOLL_CONFIG.canvas.height}px`;
  document.body.setAttribute('data-theme', state.theme);
}

function updateViewport() {
  updateViewportTransform(dollContainer);
}

// ===== Tab Switching =====
function wireTabs() {
  document.querySelectorAll('.tab-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
      document.querySelectorAll('.tab-pane').forEach(p => p.classList.remove('active'));

      btn.classList.add('active');
      const tabId = `tab-${btn.dataset.tab}`;
      document.getElementById(tabId).classList.add('active');

      setCalibrationTabActive(btn.dataset.tab === 'calibration');
      if (btn.dataset.tab === 'calibration') {
        updateCalibrateUI();
      }
    });
  });
}

// ===== Viewport Controls =====
function wireViewport() {
  document.getElementById('btn-zoom-in').addEventListener('click', () => {
    state.zoom = Math.min(state.zoom + 0.15, 2.5);
    updateViewport();
  });
  document.getElementById('btn-zoom-out').addEventListener('click', () => {
    state.zoom = Math.max(state.zoom - 0.15, 0.5);
    updateViewport();
  });
  document.getElementById('btn-reset-view').addEventListener('click', () => {
    state.zoom = 1.0;
    updateViewport();
  });
  document.getElementById('btn-grid').addEventListener('click', (e) => {
    state.showGrid = !state.showGrid;
    e.target.classList.toggle('active', state.showGrid);
    dollContainer.classList.toggle('no-grid', !state.showGrid);
  });
  document.getElementById('btn-theme').addEventListener('click', () => {
    state.theme = state.theme === 'dark' ? 'light' : 'dark';
    document.body.setAttribute('data-theme', state.theme);
  });
}

// ===== Design Operations =====
function wireDesignOps(targetContainer) {
  document.getElementById('btn-randomize').addEventListener('click', () => {
    pushHistory();
    Object.entries(DOLL_CONFIG.wardrobe).forEach(([slot, config]) => {
      const values = config.options.map(o => o.value);
      const randVal = values[Math.floor(Math.random() * values.length)];
      state.wardrobe[slot] = randVal;
      updateActiveOptionButton(slot, randVal);
    });

    const hairDyeable = DOLL_CONFIG.layers.some(l => l.category === 'hair' && l.dyeable);
    const eyesDyeable = DOLL_CONFIG.layers.some(l => l.subcategory === 'irides' && l.dyeable);

    if (hairDyeable) {
      state.dyes.hair.hue = Math.floor(Math.random() * 360);
      state.dyes.hair.sat = Math.floor(Math.random() * 150) + 50;
      state.dyes.hair.light = Math.floor(Math.random() * 100) + 50;
      syncSlider('slide-hair-hue', state.dyes.hair.hue, '\u00b0');
      syncSlider('slide-hair-sat', state.dyes.hair.sat, '%');
      syncSlider('slide-hair-light', state.dyes.hair.light, '%');
    }
    if (eyesDyeable) {
      state.dyes.eyes.hue = Math.floor(Math.random() * 360);
      syncSlider('slide-eye-hue', state.dyes.eyes.hue, '\u00b0');
    }

    renderDoll(targetContainer);
  });

  document.getElementById('btn-reset').addEventListener('click', () => {
    pushHistory();
    Object.entries(DOLL_CONFIG.wardrobe).forEach(([slot, config]) => {
      state.wardrobe[slot] = config.defaultValue;
      updateActiveOptionButton(slot, config.defaultValue);
    });

    if (DOLL_CONFIG.wardrobe.handwear) {
      state.wardrobeDepth['handwear'] = 'front_body';
      const el = document.getElementById('select-handwear-depth');
      if (el) el.value = 'front_body';
    }

    Object.keys(state.toggles).forEach(k => {
      state.toggles[k] = true;
      const el = document.getElementById(`toggle-${k}`);
      if (el) el.checked = true;
    });

    state.dyes.hair.hue = 0;
    state.dyes.hair.sat = 100;
    state.dyes.hair.light = 100;
    state.dyes.eyes.hue = 0;

    ['slide-hair-hue', 'slide-hair-sat', 'slide-hair-light', 'slide-eye-hue'].forEach(id => {
      const el = document.getElementById(id);
      if (el) {
        const isDyeValue = id.includes('sat') || id.includes('light');
        el.value = isDyeValue ? 100 : 0;
        const suffix = isDyeValue ? '%' : '\u00b0';
        document.getElementById(`val-${id}`).textContent = `${el.value}${suffix}`;
      }
    });

    document.querySelectorAll('.swatch-btn').forEach(sw => sw.classList.remove('active'));
    renderDoll(targetContainer);
  });
}

function syncSlider(id, val, suffix) {
  const el = document.getElementById(id);
  if (el) {
    el.value = val;
    document.getElementById(`val-${id}`).textContent = `${val}${suffix}`;
  }
}

// ===== Save / Load =====
function wireSaveLoad() {
  // Auto-save on page unload
  window.addEventListener('beforeunload', () => {
    saveCustomization();
  });

  // Download state JSON
  const btnSave = document.getElementById('btn-save-state');
  if (btnSave) {
    btnSave.addEventListener('click', () => downloadStateJSON());
  }

  // Load state JSON (file upload)
  const inputLoadState = document.getElementById('input-load-state');
  const btnLoadState = document.getElementById('btn-load-state');
  if (inputLoadState && btnLoadState) {
    btnLoadState.addEventListener('click', () => inputLoadState.click());
    inputLoadState.addEventListener('change', async (e) => {
      if (e.target.files.length === 0) return;
      try {
        const text = await e.target.files[0].text();
        pushHistory();
        importStateJSON(text);
        rebuildAfterStateChange();
        alert('State loaded successfully!');
      } catch (err) {
        alert(`Error loading state: ${err.message}`);
      }
      inputLoadState.value = '';
    });
  }

  // Download config
  const btnDlConfig = document.getElementById('btn-download-config');
  if (btnDlConfig) {
    btnDlConfig.addEventListener('click', () => downloadConfig());
  }

  // Download body silhouette derived from the currently loaded rig
  const btnDlSil = document.getElementById('btn-download-silhouette');
  if (btnDlSil) {
    btnDlSil.addEventListener('click', async () => {
      const origText = btnDlSil.textContent;
      btnDlSil.setAttribute('disabled', 'true');
      btnDlSil.textContent = 'Compositing silhouette...';
      try {
        await downloadBodySilhouette();
      } catch (err) {
        console.error(err);
        alert(`Failed to generate body silhouette: ${err.message}`);
      } finally {
        btnDlSil.removeAttribute('disabled');
        btnDlSil.textContent = origText;
      }
    });
  }

  // Download AI conditioning reference pack (silhouette + outline + canny + depth + pose)
  const btnDlRefPack = document.getElementById('btn-download-reference-pack');
  if (btnDlRefPack) {
    btnDlRefPack.addEventListener('click', async () => {
      const origText = btnDlRefPack.textContent;
      btnDlRefPack.setAttribute('disabled', 'true');
      btnDlRefPack.textContent = 'Rendering channels...';
      try {
        await downloadReferencePack();
      } catch (err) {
        console.error(err);
        alert(`Failed to generate reference pack: ${err.message}`);
      } finally {
        btnDlRefPack.removeAttribute('disabled');
        btnDlRefPack.textContent = origText;
      }
    });
  }

  // Download authoring guide templates
  const btnDlGuides = document.getElementById('btn-download-guides');
  if (btnDlGuides) {
    btnDlGuides.addEventListener('click', async () => {
      const origText = btnDlGuides.textContent;
      btnDlGuides.setAttribute('disabled', 'true');
      btnDlGuides.textContent = 'Rendering guides...';
      try {
        const res = await fetch('/api/guide-templates.zip');
        if (!res.ok) throw new Error(`Server returned ${res.status}`);
        const blob = await res.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = 'paperdoll_guides.zip';
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
      } catch (err) {
        console.error(err);
        alert(`Failed to download guide templates: ${err.message}`);
      } finally {
        btnDlGuides.removeAttribute('disabled');
        btnDlGuides.textContent = origText;
      }
    });
  }

  // Export ZIP
  const btnExportZip = document.getElementById('btn-export-zip');
  if (btnExportZip) {
    btnExportZip.addEventListener('click', async () => {
      const btn = btnExportZip;
      const origText = btn.textContent;
      btn.setAttribute('disabled', 'true');
      btn.textContent = 'Creating ZIP package...';
      try {
        await exportZIP();
      } catch (err) {
        console.error(err);
        alert(`Failed to export ZIP package: ${err.message}`);
      } finally {
        btn.removeAttribute('disabled');
        btn.textContent = origText;
      }
    });
  }
}

function rebuildAfterStateChange() {
  // Sync UI to current state
  const targetContainer = document.getElementById('doll-layers-target');
  buildUI(targetContainer);

  Object.entries(state.wardrobe).forEach(([slot, val]) => {
    updateActiveOptionButton(slot, val);
  });

  Object.entries(state.toggles).forEach(([groupId, val]) => {
    const el = document.getElementById(`toggle-${groupId}`);
    if (el) el.checked = val;
  });

  syncSlider('slide-hair-hue', state.dyes.hair.hue, '\u00b0');
  syncSlider('slide-hair-sat', state.dyes.hair.sat, '%');
  syncSlider('slide-hair-light', state.dyes.hair.light, '%');
  syncSlider('slide-eye-hue', state.dyes.eyes.hue, '\u00b0');

  document.body.setAttribute('data-theme', state.theme);
  dollContainer.classList.toggle('no-grid', !state.showGrid);
  const gridBtn = document.getElementById('btn-grid');
  if (gridBtn) gridBtn.classList.toggle('active', state.showGrid);

  updateViewport();
  updateCalibrateUI();
  renderDoll(targetContainer);
}

// ===== Undo / Redo =====
function wireUndoRedo(targetContainer) {
  const btnUndo = document.getElementById('btn-undo');
  const btnRedo = document.getElementById('btn-redo');

  if (btnUndo) {
    btnUndo.addEventListener('click', () => {
      if (undo()) {
        rebuildAfterStateChange();
      }
    });
  }
  if (btnRedo) {
    btnRedo.addEventListener('click', () => {
      if (redo()) {
        rebuildAfterStateChange();
      }
    });
  }

  // Keyboard shortcuts
  window.addEventListener('keydown', (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === 'z') {
      e.preventDefault();
      if (e.shiftKey) {
        if (redo()) rebuildAfterStateChange();
      } else {
        if (undo()) rebuildAfterStateChange();
      }
    }
  });
}

// ===== Checkbox Visibility =====
function wireCheckboxVisibility() {
  const chkChroma = document.getElementById('chk-chromakey');
  const divChroma = document.getElementById('chromakey-controls');
  const chkSubtract = document.getElementById('chk-subtract-body');
  const divSubtract = document.getElementById('subtract-body-controls');

  function updateVisibility() {
    if (divChroma && chkChroma) divChroma.style.display = chkChroma.checked ? 'flex' : 'none';
    if (divSubtract && chkSubtract) divSubtract.style.display = chkSubtract.checked ? 'flex' : 'none';
  }

  if (chkChroma) chkChroma.addEventListener('change', updateVisibility);
  if (chkSubtract) chkSubtract.addEventListener('change', updateVisibility);
  updateVisibility();
}

// ===== Start =====
init().catch(err => {
  console.error('Failed to initialize Paper Doll Studio:', err);
  document.body.innerHTML = `<div style="padding:2rem;text-align:center;color:var(--danger-color);">
    <h2>Failed to Load</h2>
    <p>${err.message}</p>
    <p>Make sure project.json or doll_config.js exists in the project root.</p>
  </div>`;
});
