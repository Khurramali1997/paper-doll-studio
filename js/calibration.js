import { state, DOLL_CONFIG, pushHistory } from './state.js';
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

let isCalibrationTabActive = false;

export function initCalibration(targetContainer) {
  wireDPad(targetContainer);
  wireCalibrateCopy();
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
