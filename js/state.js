import { isHandwearRight, isHandwearLeft } from './utils.js';

export const TOGGLE_GROUPS = {
  'hair_front': { name: 'Front Hair (Bangs)', subcats: ['hair_front'] },
  'hair_back': { name: 'Back Hair (Main)', subcats: ['hair_back'] },
  'eyes': { name: 'Eyes (Irides & Whites)', subcats: ['eyewhite', 'irides'] },
  'eyelashes': { name: 'Eyelashes', subcats: ['eyelashes'] },
  'eyebrows': { name: 'Eyebrows', subcats: ['eyebrows'] },
  'nose': { name: 'Nose', subcats: ['nose'] },
  'mouth': { name: 'Mouth', subcats: ['mouth'] },
  'ears': { name: 'Ears', subcats: ['ears'] }
};

// Project configuration (layers, wardrobe slots, canvas)
export let DOLL_CONFIG = null;

// Current customization state
export const state = {
  wardrobe: {},
  wardrobeDepth: {},
  toggles: {},
  layerControls: {},
  dyes: {
    hair: { hue: 0, sat: 100, light: 100 },
    eyes: { hue: 0 }
  },
  zoom: 1.0,
  showGrid: true,
  theme: 'dark',
  offsets: {}
};

// Undo / Redo history
const MAX_HISTORY = 50;
let undoStack = [];
let redoStack = [];

function snapshot() {
  return {
    wardrobe: JSON.parse(JSON.stringify(state.wardrobe)),
    wardrobeDepth: JSON.parse(JSON.stringify(state.wardrobeDepth)),
    toggles: JSON.parse(JSON.stringify(state.toggles)),
    layerControls: JSON.parse(JSON.stringify(state.layerControls)),
    dyes: JSON.parse(JSON.stringify(state.dyes)),
    offsets: JSON.parse(JSON.stringify(state.offsets))
  };
}

function applySnapshot(snap) {
  state.wardrobe = snap.wardrobe;
  state.wardrobeDepth = snap.wardrobeDepth;
  state.toggles = snap.toggles;
  state.layerControls = snap.layerControls || {};
  state.dyes = snap.dyes;
  state.offsets = snap.offsets;
}

export function pushHistory() {
  undoStack.push(snapshot());
  if (undoStack.length > MAX_HISTORY) undoStack.shift();
  redoStack = [];
}

export function undo() {
  if (undoStack.length === 0) return false;
  redoStack.push(snapshot());
  applySnapshot(undoStack.pop());
  return true;
}

export function redo() {
  if (redoStack.length === 0) return false;
  undoStack.push(snapshot());
  applySnapshot(redoStack.pop());
  return true;
}

export function canUndo() {
  return undoStack.length > 0;
}

export function canRedo() {
  return redoStack.length > 0;
}

// Load project config from project.json (primary) or window.DOLL_CONFIG (fallback)
export async function loadProjectConfig() {
  try {
    const resp = await fetch('project.json');
    if (resp.ok) {
      DOLL_CONFIG = await resp.json();
      migrateConfig();
      console.log(`Loaded project.json (${DOLL_CONFIG.layers.length} layers)`);
      return;
    }
  } catch (_) { /* fall through */ }

  if (window.DOLL_CONFIG) {
    DOLL_CONFIG = window.DOLL_CONFIG;
    migrateConfig();
    console.log('Loaded window.DOLL_CONFIG (no project.json found)');
    return;
  }

  throw new Error('No project configuration found. Place project.json or doll_config.js in the root.');
}

function migrateConfig() {
  if (!DOLL_CONFIG.defaults) {
    DOLL_CONFIG.defaults = { theme: 'dark', zoom: 1.0, showGrid: true, offsets: {} };
  }
  if (!DOLL_CONFIG.defaults.offsets) {
    DOLL_CONFIG.defaults.offsets = {};
  }
  if (typeof DOLL_CONFIG.version === 'undefined') {
    DOLL_CONFIG.version = 1;
  }
}

export function initializeState() {
  Object.entries(DOLL_CONFIG.wardrobe).forEach(([slot, config]) => {
    state.wardrobe[slot] = config.defaultValue;
  });

  DOLL_CONFIG.layers.forEach(layer => {
    if (layer.toggleable) {
      const toggleGroupId = Object.keys(TOGGLE_GROUPS).find(groupId =>
        TOGGLE_GROUPS[groupId].subcats.includes(layer.subcategory)
      );
      if (toggleGroupId && state.toggles[toggleGroupId] === undefined) {
        state.toggles[toggleGroupId] = layer.defaultVisible !== false;
      }
    }
  });

  const configOffsets = DOLL_CONFIG.defaults?.offsets || {};
  state.offsets = JSON.parse(JSON.stringify(configOffsets));

  if (!state.offsets['rig_offset']) {
    state.offsets['rig_offset'] = { x: 0, y: 0 };
  }

  if (!state.offsets['clothed_assets']) {
    state.offsets['clothed_assets'] = { x: 0, y: 0 };
  }

  DOLL_CONFIG.layers.forEach(layer => {
    if (layer.category && !state.offsets[layer.category]) {
      state.offsets[layer.category] = { x: 0, y: 0 };
    }
    if (layer.subcategory && !state.offsets[layer.subcategory]) {
      state.offsets[layer.subcategory] = { x: 0, y: 0 };
    }
  });

  state.zoom = DOLL_CONFIG.defaults?.zoom || 1.0;
  state.showGrid = DOLL_CONFIG.defaults?.showGrid !== false;
  state.theme = DOLL_CONFIG.defaults?.theme || 'dark';
}

function computeZForLayer(layer) {
  let finalZ = layer.z;
  if (layer.subcategory === 'handwear') {
    const isClothing = layer.optionValue !== 'skin_wear';
    const isRight = isHandwearRight(layer.id, layer.name);
    const isLeft = isHandwearLeft(layer.id, layer.name);

    if (isRight) {
      finalZ = isClothing ? 15 : 14;
    } else if (isLeft) {
      finalZ = isClothing ? 260 : 259;
    }
  }
  const controls = state.layerControls[layer.id];
  if (controls && Number.isFinite(controls.zOffset)) {
    finalZ += controls.zOffset;
  }
  return finalZ;
}

export function getActiveLayers() {
  const active = [];

  // When dress clothing is active, topwear and bottomwear show skin base only
  const effectiveWardrobe = { ...state.wardrobe };
  if (effectiveWardrobe.dress === 'clothing') {
    effectiveWardrobe.topwear = 'skin_wear';
    effectiveWardrobe.bottomwear = 'skin_wear';
  }

  DOLL_CONFIG.layers.forEach(layer => {
    const controls = state.layerControls[layer.id];
    if (controls?.visible === false) return;

    if (layer.category === 'wardrobe') {
      const slot = layer.subcategory;
      const activeOptionVal = effectiveWardrobe[slot];
      const slotConfig = DOLL_CONFIG.wardrobe[slot];
      if (slotConfig) {
        const selectedOption = slotConfig.options.find(o => o.value === activeOptionVal);
        if (selectedOption && selectedOption.layers.includes(layer.id)) {
          active.push(layer);
        }
      }
    } else {
      let isVisible = true;
      const toggleGroupId = Object.keys(TOGGLE_GROUPS).find(groupId =>
        TOGGLE_GROUPS[groupId].subcats.includes(layer.subcategory)
      );
      if (toggleGroupId !== undefined) {
        isVisible = state.toggles[toggleGroupId] !== false;
      }
      if (isVisible) {
        active.push(layer);
      }
    }
  });

  return active.map(l => ({
    ...l,
    name: state.layerControls[l.id]?.customName || l.name,
    computedZ: computeZForLayer(l),
    opacity: state.layerControls[l.id]?.opacity ?? 100,
  })).sort((a, b) => a.computedZ - b.computedZ);
}

export function getBaseLayers() {
  return DOLL_CONFIG.layers.filter(layer => {
    if (layer.category === 'wardrobe') return layer.optionValue === 'skin_wear';
    return true;
  }).map(l => {
    let finalZ = l.z;
    if (l.subcategory === 'handwear') {
      const isClothing = l.optionValue !== 'skin_wear';
      const isRight = isHandwearRight(l.id, l.name);
      const isLeft = isHandwearLeft(l.id, l.name);
      if (isRight) finalZ = isClothing ? 15 : 14;
      else if (isLeft) finalZ = isClothing ? 260 : 259;
    }
    return { ...l, computedZ: finalZ };
  }).sort((a, b) => a.computedZ - b.computedZ);
}

// Save / Load character customization states

const SAVE_KEY = 'paperdoll_customization';

export function saveCustomization() {
  const data = {
    version: 1,
    wardrobe: state.wardrobe,
    wardrobeDepth: state.wardrobeDepth,
    toggles: state.toggles,
    layerControls: state.layerControls,
    dyes: state.dyes,
    offsets: state.offsets,
    savedAt: new Date().toISOString()
  };
  localStorage.setItem(SAVE_KEY, JSON.stringify(data));
  return data;
}

export function loadCustomization() {
  try {
    const raw = localStorage.getItem(SAVE_KEY);
    if (!raw) return false;
    const data = JSON.parse(raw);
    if (data.version !== 1) return false;

    state.wardrobe = { ...state.wardrobe, ...data.wardrobe };
    state.wardrobeDepth = { ...state.wardrobeDepth, ...(data.wardrobeDepth || {}) };
    state.toggles = { ...state.toggles, ...data.toggles };
    state.layerControls = { ...state.layerControls, ...(data.layerControls || {}) };
    state.dyes = { ...state.dyes, ...data.dyes };
    state.offsets = { ...state.offsets, ...(data.offsets || {}) };
    return true;
  } catch {
    return false;
  }
}

export function clearSavedCustomization() {
  localStorage.removeItem(SAVE_KEY);
}

export function exportStateJSON() {
  const data = {
    version: 1,
    wardrobe: state.wardrobe,
    wardrobeDepth: state.wardrobeDepth,
    toggles: state.toggles,
    layerControls: state.layerControls,
    dyes: state.dyes,
    offsets: state.offsets,
    zoom: state.zoom,
    theme: state.theme,
    showGrid: state.showGrid,
    exportedAt: new Date().toISOString()
  };
  return JSON.stringify(data, null, 2);
}

export function importStateJSON(jsonStr) {
  const data = JSON.parse(jsonStr);
  if (data.version !== 1) throw new Error('Unsupported state version');

  state.wardrobe = { ...state.wardrobe, ...data.wardrobe };
  if (data.wardrobeDepth) state.wardrobeDepth = { ...state.wardrobeDepth, ...data.wardrobeDepth };
  state.toggles = { ...state.toggles, ...data.toggles };
  if (data.layerControls) state.layerControls = { ...state.layerControls, ...data.layerControls };
  state.dyes = { ...state.dyes, ...data.dyes };
  if (data.offsets) state.offsets = { ...state.offsets, ...data.offsets };
  if (data.zoom !== undefined) state.zoom = data.zoom;
  if (data.theme) state.theme = data.theme;
  if (data.showGrid !== undefined) state.showGrid = data.showGrid;
}
