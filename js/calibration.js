import { state, DOLL_CONFIG, TOGGLE_GROUPS, pushHistory } from './state.js';
import { renderDoll } from './render.js';

export const selectCalibrateLayer = document.getElementById('select-calibrate-layer');
export const valCalibrateX = document.getElementById('val-calibrate-x');
export const valCalibrateY = document.getElementById('val-calibrate-y');
export const txtCalibrationCode = document.getElementById('txt-calibration-code');
export const btnCopyCalibration = document.getElementById('btn-copy-calibration');

const dpadUp = document.getElementById('dpad-up');
const dpadDown = document.getElementById('dpad-down');
const dpadLeft = document.getElementById('dpad-left');
const dpadRight = document.getElementById('dpad-right');
const btnCalibrateResetLayer = document.getElementById('btn-calibrate-reset-layer');
const btnCalibrateResetAll = document.getElementById('btn-calibrate-reset-all');
const calibrationLayerVisibility = document.getElementById('calibration-layer-visibility');
const btnCalibrateShowAll = document.getElementById('btn-calibrate-show-all');
const btnCalibrateSoloGroup = document.getElementById('btn-calibrate-solo-group');
const btnCalibrateHideWardrobe = document.getElementById('btn-calibrate-hide-wardrobe');

let isCalibrationTabActive = false;

export function initCalibration(targetContainer) {
  wireDPad(targetContainer);
  wireCalibrateCopy();
  wireCalibrationVisibility(targetContainer);
  selectCalibrateLayer.addEventListener('change', () => updateCalibrateUI());
}

export function setCalibrationTabActive(active) {
  isCalibrationTabActive = active;
  if (active) updateCalibrateUI();
}

export function getSelectedCalibrateGroup() {
  return selectCalibrateLayer.value;
}

export function updateCalibrateUI() {
  const group = getSelectedCalibrateGroup();
  if (!group) return;
  const offset = state.offsets[group] || { x: 0, y: 0 };
  valCalibrateX.textContent = `${offset.x}px`;
  valCalibrateY.textContent = `${offset.y}px`;
  txtCalibrationCode.value = JSON.stringify(state.offsets, null, 2);
  renderCalibrationVisibility();
}

export function adjustOffset(dx, dy, targetContainer) {
  const group = getSelectedCalibrateGroup();
  if (!group) return;
  pushHistory();
  if (!state.offsets[group]) state.offsets[group] = { x: 0, y: 0 };
  state.offsets[group].x += dx;
  state.offsets[group].y += dy;
  updateCalibrateUI();
  renderDoll(targetContainer);
}

function wireDPad(targetContainer) {
  dpadUp.addEventListener('click', (e) => adjustOffset(0, -1 * (e.shiftKey ? 5 : 1), targetContainer));
  dpadDown.addEventListener('click', (e) => adjustOffset(0, 1 * (e.shiftKey ? 5 : 1), targetContainer));
  dpadLeft.addEventListener('click', (e) => adjustOffset(-1 * (e.shiftKey ? 5 : 1), 0, targetContainer));
  dpadRight.addEventListener('click', (e) => adjustOffset(1 * (e.shiftKey ? 5 : 1), 0, targetContainer));

  btnCalibrateResetLayer.addEventListener('click', () => {
    const group = getSelectedCalibrateGroup();
    if (group) {
      pushHistory();
      state.offsets[group] = { x: 0, y: 0 };
      updateCalibrateUI();
      renderDoll(targetContainer);
    }
  });

  btnCalibrateResetAll.addEventListener('click', () => {
    pushHistory();
    Object.keys(state.offsets).forEach(k => {
      state.offsets[k] = { x: 0, y: 0 };
    });
    updateCalibrateUI();
    renderDoll(targetContainer);
  });

  // Keyboard controls
  window.addEventListener('keydown', (e) => {
    if (!isCalibrationTabActive) return;
    const step = e.shiftKey ? 5 : 1;
    if (e.key === 'ArrowUp') { e.preventDefault(); adjustOffset(0, -step, targetContainer); }
    else if (e.key === 'ArrowDown') { e.preventDefault(); adjustOffset(0, step, targetContainer); }
    else if (e.key === 'ArrowLeft') { e.preventDefault(); adjustOffset(-step, 0, targetContainer); }
    else if (e.key === 'ArrowRight') { e.preventDefault(); adjustOffset(step, 0, targetContainer); }
  });
}

function ensureLayerControls(layerId) {
  if (!state.layerControls[layerId]) {
    state.layerControls[layerId] = { visible: true, opacity: 100, zOffset: 0 };
  }
  const controls = state.layerControls[layerId];
  if (controls.visible === undefined) controls.visible = true;
  if (!Number.isFinite(controls.opacity)) controls.opacity = 100;
  if (!Number.isFinite(controls.zOffset)) controls.zOffset = 0;
  return controls;
}

function layerMatchesGroup(layer, group) {
  if (group === 'rig_offset') return true;
  if (group === 'clothed_assets') return layer.category === 'wardrobe';
  return layer.category === group || layer.subcategory === group;
}

function toggleGroupForLayer(layer) {
  return Object.keys(TOGGLE_GROUPS).find(groupId =>
    TOGGLE_GROUPS[groupId].subcats.includes(layer.subcategory)
  );
}

function isLayerGroupVisible(layer) {
  const groupId = toggleGroupForLayer(layer);
  return !groupId || state.toggles[groupId] !== false;
}

function syncAppearanceToggleInputs() {
  Object.entries(state.toggles).forEach(([groupId, val]) => {
    const el = document.getElementById(`toggle-${groupId}`);
    if (el) el.checked = val !== false;
  });
}

function selectedWardrobeLayerIds() {
  const ids = new Set();
  Object.entries(DOLL_CONFIG.wardrobe).forEach(([slot, slotConfig]) => {
    const selected = slotConfig.options.find(o => o.value === state.wardrobe[slot]);
    selected?.layers.forEach(id => ids.add(id));
  });
  return ids;
}

function calibrationLayerRows() {
  const selectedWardrobe = selectedWardrobeLayerIds();
  return DOLL_CONFIG.layers
    .filter(layer => layer.category !== 'wardrobe' || selectedWardrobe.has(layer.id))
    .map(layer => ({
      layer,
      controls: ensureLayerControls(layer.id),
      inTarget: layerMatchesGroup(layer, getSelectedCalibrateGroup()),
    }))
    .sort((a, b) => {
      if (a.inTarget !== b.inTarget) return a.inTarget ? -1 : 1;
      return (a.layer.z || 0) - (b.layer.z || 0);
    });
}

function renderCalibrationVisibility() {
  if (!calibrationLayerVisibility || !DOLL_CONFIG) return;
  calibrationLayerVisibility.textContent = '';
  const rows = calibrationLayerRows();

  rows.forEach(({ layer, controls, inTarget }) => {
    const isVisible = controls.visible !== false && isLayerGroupVisible(layer);
    const row = document.createElement('label');
    row.className = `calibration-layer-row${inTarget ? ' target' : ''}${!isVisible ? ' muted' : ''}`;

    const checkbox = document.createElement('input');
    checkbox.type = 'checkbox';
    checkbox.checked = isVisible;
    checkbox.addEventListener('change', () => {
      pushHistory();
      controls.visible = checkbox.checked;
      if (checkbox.checked) {
        const groupId = toggleGroupForLayer(layer);
        if (groupId) state.toggles[groupId] = true;
      }
      syncAppearanceToggleInputs();
      renderCalibrationVisibility();
      renderDoll(document.getElementById('doll-layers-target'));
    });
    row.appendChild(checkbox);

    const meta = document.createElement('span');
    meta.className = 'calibration-layer-meta';
    const name = document.createElement('span');
    name.className = 'calibration-layer-name';
    name.textContent = state.layerControls[layer.id]?.customName || layer.name || layer.id;
    const sub = document.createElement('span');
    sub.className = 'calibration-layer-sub';
    sub.textContent = `${layer.category || 'layer'} · ${layer.subcategory || 'base'} · z ${layer.z}`;
    meta.appendChild(name);
    meta.appendChild(sub);
    row.appendChild(meta);

    calibrationLayerVisibility.appendChild(row);
  });
}

function wireCalibrationVisibility(targetContainer) {
  btnCalibrateShowAll?.addEventListener('click', () => {
    pushHistory();
    DOLL_CONFIG.layers.forEach(layer => {
      ensureLayerControls(layer.id).visible = true;
    });
    Object.keys(state.toggles).forEach(groupId => {
      state.toggles[groupId] = true;
    });
    syncAppearanceToggleInputs();
    renderCalibrationVisibility();
    renderDoll(targetContainer);
  });

  btnCalibrateSoloGroup?.addEventListener('click', () => {
    const group = getSelectedCalibrateGroup();
    if (!group) return;
    pushHistory();
    DOLL_CONFIG.layers.forEach(layer => {
      ensureLayerControls(layer.id).visible = layerMatchesGroup(layer, group);
    });
    Object.keys(state.toggles).forEach(groupId => {
      state.toggles[groupId] = true;
    });
    syncAppearanceToggleInputs();
    renderCalibrationVisibility();
    renderDoll(targetContainer);
  });

  btnCalibrateHideWardrobe?.addEventListener('click', () => {
    pushHistory();
    DOLL_CONFIG.layers.forEach(layer => {
      if (layer.category === 'wardrobe') ensureLayerControls(layer.id).visible = false;
      else ensureLayerControls(layer.id).visible = true;
    });
    Object.keys(state.toggles).forEach(groupId => {
      state.toggles[groupId] = true;
    });
    syncAppearanceToggleInputs();
    renderCalibrationVisibility();
    renderDoll(targetContainer);
  });
}

function wireCalibrateCopy() {
  btnCopyCalibration.addEventListener('click', () => {
    navigator.clipboard.writeText(txtCalibrationCode.value)
      .then(() => {
        const originalText = btnCopyCalibration.textContent;
        btnCopyCalibration.textContent = 'Copied!';
        btnCopyCalibration.style.borderColor = 'var(--success-color)';
        btnCopyCalibration.style.color = 'var(--success-color)';
        setTimeout(() => {
          btnCopyCalibration.textContent = originalText;
          btnCopyCalibration.style.borderColor = '';
          btnCopyCalibration.style.color = '';
        }, 1500);
      })
      .catch(err => console.error('Failed to copy config: ', err));
  });
}

export function buildCalibrateOptions() {
  selectCalibrateLayer.innerHTML = '';
  const calibrateOptions = [
    { value: 'rig_offset', text: 'Entire Rig (Global)' },
    { value: 'clothed_assets', text: 'All Clothed Assets (Global)' },
  ];

  const categoriesSeen = new Set();
  const subcategoriesSeen = new Set();
  DOLL_CONFIG.layers.forEach(layer => {
    if (layer.category) categoriesSeen.add(layer.category);
    if (layer.subcategory) subcategoriesSeen.add(layer.subcategory);
  });

  Object.keys(DOLL_CONFIG.wardrobe).forEach(slot => {
    calibrateOptions.push({ value: slot, text: `${slot.charAt(0).toUpperCase() + slot.slice(1)} Layers` });
    subcategoriesSeen.delete(slot);
  });

  categoriesSeen.forEach(cat => {
    if (cat !== 'wardrobe') {
      calibrateOptions.push({ value: cat, text: `${cat.toUpperCase()} Layers` });
    }
  });

  calibrateOptions.forEach(opt => {
    const oEl = document.createElement('option');
    oEl.value = opt.value;
    oEl.textContent = opt.text;
    selectCalibrateLayer.appendChild(oEl);
  });
}
