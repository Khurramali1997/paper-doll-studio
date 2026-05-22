// Local Image & Blob Caches for client-side PSD/asset processing
let localImageCache = {};
let localBlobCache = {};
let pendingAssetFile = null;
let pendingAssetImage = null;
let mlBgModule = null;

// Dynamic State Management
const state = {
  // Wardrobe active selections: { slot: optionValue }
  wardrobe: {},
  
  // Depth overrides (e.g. handwear)
  wardrobeDepth: {},

  // Toggle states for toggleable groups
  toggles: {},

  // CSS Dye Filters
  dyes: {
    hair: { hue: 0, sat: 100, light: 100 },
    eyes: { hue: 0 }
  },

  // Viewport Settings
  zoom: DOLL_CONFIG.defaults?.zoom || 1.0,
  showGrid: DOLL_CONFIG.defaults?.showGrid !== false,
  theme: DOLL_CONFIG.defaults?.theme || 'dark',

  // Calibration Offsets (x, y) per category/subcategory
  offsets: {}
};

// Toggle Groups configuration mappings
const TOGGLE_GROUPS = {
  'hair_front': { name: 'Front Hair (Bangs)', subcats: ['hair_front'] },
  'hair_back': { name: 'Back Hair (Main)', subcats: ['hair_back'] },
  'eyes': { name: 'Eyes (Irides & Whites)', subcats: ['eyewhite', 'irides'] },
  'eyelashes': { name: 'Eyelashes', subcats: ['eyelashes'] },
  'eyebrows': { name: 'Eyebrows', subcats: ['eyebrows'] },
  'nose': { name: 'Nose', subcats: ['nose'] },
  'mouth': { name: 'Mouth', subcats: ['mouth'] },
  'ears': { name: 'Ears', subcats: ['ears'] }
};

// DOM Elements
const targetContainer = document.getElementById('doll-layers-target');
const dollContainer = document.getElementById('doll-container');
const txtDimension = document.getElementById('txt-dimension');
const selectCalibrateLayer = document.getElementById('select-calibrate-layer');
const valCalibrateX = document.getElementById('val-calibrate-x');
const valCalibrateY = document.getElementById('val-calibrate-y');
const txtCalibrationCode = document.getElementById('txt-calibration-code');
const btnCopyCalibration = document.getElementById('btn-copy-calibration');

const dpadUp = document.getElementById('dpad-up');
const dpadDown = document.getElementById('dpad-down');
const dpadLeft = document.getElementById('dpad-left');
const dpadRight = document.getElementById('dpad-right');

const btnCalibrateResetLayer = document.getElementById('btn-calibrate-reset-layer');
const btnCalibrateResetAll = document.getElementById('btn-calibrate-reset-all');

// Initialize State dynamically from DOLL_CONFIG
function initializeState() {
  // Wardrobe slots
  Object.entries(DOLL_CONFIG.wardrobe).forEach(([slot, config]) => {
    state.wardrobe[slot] = config.defaultValue;
  });

  // Toggles
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

  // Calibration Offsets (preloading if present)
  const configOffsets = DOLL_CONFIG.defaults?.offsets || {};
  state.offsets = JSON.parse(JSON.stringify(configOffsets));

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

  // Set initial canvas dimension and container styling
  txtDimension.textContent = `Canvas: ${DOLL_CONFIG.canvas.width} × ${DOLL_CONFIG.canvas.height} px`;
  dollContainer.style.width = `${DOLL_CONFIG.canvas.width}px`;
  dollContainer.style.height = `${DOLL_CONFIG.canvas.height}px`;
  
  // Theme
  document.body.setAttribute('data-theme', state.theme);
}

// Build UI sidebars dynamically
function buildUI() {
  // 1. Build Wardrobe Tab options
  const wardrobeContainer = document.getElementById('wardrobe-options-container');
  wardrobeContainer.innerHTML = '';

  Object.entries(DOLL_CONFIG.wardrobe).forEach(([slot, slotConfig]) => {
    const groupDiv = document.createElement('div');
    groupDiv.className = 'control-group';
    
    const title = document.createElement('h3');
    title.textContent = `${slotConfig.name || slot.replace("wear", "wear").toUpperCase()} Layer`;
    groupDiv.appendChild(title);

    const gridDiv = document.createElement('div');
    gridDiv.className = 'option-grid';

    slotConfig.options.forEach(opt => {
      const btn = document.createElement('button');
      btn.className = `option-btn ${state.wardrobe[slot] === opt.value ? 'active' : ''}`;
      btn.dataset.slot = slot;
      btn.dataset.val = opt.value;

      // Select matching styles for option preview boxes
      let previewClass = 'none-bg';
      let previewText = '';
      if (opt.value === 'skin_wear') {
        previewClass = 'skin-bg';
      } else if (opt.value === 'clothing') {
        if (slot === 'topwear') previewClass = 'cloth-top-bg';
        else if (slot === 'bottomwear') previewClass = 'cloth-bot-bg';
        else if (slot === 'legwear') previewClass = 'cloth-leg-bg';
        else if (slot === 'handwear') previewClass = 'cloth-hand-bg';
        else previewClass = 'cloth-generic-bg';
      } else if (opt.value === 'none') {
        previewText = '❌';
      } else {
        previewClass = 'cloth-generic-bg';
        previewText = opt.name.charAt(0);
      }

      const previewSpan = document.createElement('span');
      previewSpan.className = `option-preview ${previewClass}`;
      if (previewText) previewSpan.textContent = previewText;
      btn.appendChild(previewSpan);

      const titleSpan = document.createElement('span');
      titleSpan.className = 'option-title';
      titleSpan.textContent = opt.name;
      btn.appendChild(titleSpan);

      btn.addEventListener('click', () => {
        gridDiv.querySelectorAll('.option-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        state.wardrobe[slot] = opt.value;
        renderDoll();
      });

      gridDiv.appendChild(btn);
    });

    groupDiv.appendChild(gridDiv);
    wardrobeContainer.appendChild(groupDiv);
  });

  // 1b. Depth overrides
  const depthContainer = document.getElementById('depth-controls-container');
  depthContainer.innerHTML = '';
  if (DOLL_CONFIG.wardrobe.handwear) {
    const wrapper = document.createElement('div');
    wrapper.className = 'select-wrapper';
    wrapper.style.marginTop = '0.8rem';

    const label = document.createElement('label');
    label.htmlFor = 'select-handwear-depth';
    label.style.cssText = 'font-size: 0.75rem; color: var(--text-secondary); display: block; margin-bottom: 0.3rem;';
    label.textContent = 'Drawing Order (Depth):';
    wrapper.appendChild(label);

    const select = document.createElement('select');
    select.id = 'select-handwear-depth';
    select.style.cssText = 'width: 100%; padding: 0.5rem; border-radius: 6px; background: var(--bg-secondary); border: 1px solid var(--border-glass); color: var(--text-primary); font-family: var(--font-main); outline: none; font-size: 0.8rem;';
    
    const opts = [
      { value: 'behind', text: 'Behind Body (Z-Index: 15)' },
      { value: 'front_body', text: 'In Front of Body, Behind Clothes (Z-Index: 165)' },
      { value: 'front_clothes', text: 'On Top of Clothes (Z-Index: 260)' }
    ];
    opts.forEach(o => {
      const optEl = document.createElement('option');
      optEl.value = o.value;
      optEl.textContent = o.text;
      if (o.value === 'front_body') optEl.selected = true;
      select.appendChild(optEl);
    });

    select.addEventListener('change', (e) => {
      state.wardrobeDepth['handwear'] = e.target.value;
      renderDoll();
    });
    state.wardrobeDepth['handwear'] = 'front_body';

    wrapper.appendChild(select);
    depthContainer.appendChild(wrapper);
  }

  // 2. Build Appearance Tab options
  const toggleContainer = document.getElementById('appearance-toggles-container');
  toggleContainer.innerHTML = '';

  const hairGroup = document.createElement('div');
  hairGroup.className = 'control-group';
  hairGroup.innerHTML = '<h3>Hair Elements</h3>';
  const hairList = document.createElement('div');
  hairList.className = 'toggle-list';
  hairGroup.appendChild(hairList);

  const faceGroup = document.createElement('div');
  faceGroup.className = 'control-group';
  faceGroup.innerHTML = '<h3>Face Elements</h3>';
  const faceList = document.createElement('div');
  faceList.className = 'toggle-list';
  faceGroup.appendChild(faceList);

  let hasHairToggles = false;
  let hasFaceToggles = false;

  Object.entries(TOGGLE_GROUPS).forEach(([groupId, config]) => {
    const matchingLayers = DOLL_CONFIG.layers.filter(l => l.toggleable && config.subcats.includes(l.subcategory));
    if (matchingLayers.length === 0) return;

    const label = document.createElement('label');
    label.className = 'switch-item';

    const nameSpan = document.createElement('span');
    nameSpan.className = 'switch-label';
    nameSpan.textContent = config.name;
    label.appendChild(nameSpan);

    const checkbox = document.createElement('input');
    checkbox.type = 'checkbox';
    checkbox.id = `toggle-${groupId}`;
    checkbox.checked = state.toggles[groupId] !== false;
    checkbox.addEventListener('change', (e) => {
      state.toggles[groupId] = e.target.checked;
      renderDoll();
    });
    label.appendChild(checkbox);

    const sliderSpan = document.createElement('span');
    sliderSpan.className = 'slider';
    label.appendChild(sliderSpan);

    if (groupId.startsWith('hair')) {
      hairList.appendChild(label);
      hasHairToggles = true;
    } else {
      faceList.appendChild(label);
      hasFaceToggles = true;
    }
  });

  if (hasHairToggles) toggleContainer.appendChild(hairGroup);
  if (hasFaceToggles) toggleContainer.appendChild(faceGroup);

  // Dye controls
  const slidersContainer = document.getElementById('dye-sliders-container');
  slidersContainer.innerHTML = '';

  const dyeGroup = document.createElement('div');
  dyeGroup.className = 'control-group';
  dyeGroup.innerHTML = '<h3>Dynamic Dye Colors</h3><p class="group-desc">Apply CSS real-time filter adjustments to customize colors.</p>';

  const hairDyeable = DOLL_CONFIG.layers.some(l => l.category === 'hair' && l.dyeable);
  const eyesDyeable = DOLL_CONFIG.layers.some(l => l.subcategory === 'irides' && l.dyeable);

  if (hairDyeable) {
    dyeGroup.appendChild(createSliderBlock('Hair Hue', 'slide-hair-hue', 0, 360, state.dyes.hair.hue, '°', (val) => {
      state.dyes.hair.hue = val;
      renderDoll();
    }));
    dyeGroup.appendChild(createSliderBlock('Hair Saturation', 'slide-hair-sat', 0, 250, state.dyes.hair.sat, '%', (val) => {
      state.dyes.hair.sat = val;
      renderDoll();
    }));
    dyeGroup.appendChild(createSliderBlock('Hair Brightness', 'slide-hair-light', 20, 200, state.dyes.hair.light, '%', (val) => {
      state.dyes.hair.light = val;
      renderDoll();
    }));
  }

  if (eyesDyeable) {
    if (hairDyeable) {
      const div = document.createElement('div');
      div.className = 'divider';
      dyeGroup.appendChild(div);
    }
    dyeGroup.appendChild(createSliderBlock('Eye Color (Irides Hue)', 'slide-eye-hue', 0, 360, state.dyes.eyes.hue, '°', (val) => {
      state.dyes.eyes.hue = val;
      renderDoll();
    }));
  }

  if (hairDyeable || eyesDyeable) {
    slidersContainer.appendChild(dyeGroup);
  }

  // Helper slider generator
  function createSliderBlock(title, id, min, max, val, suffix, onChange) {
    const block = document.createElement('div');
    block.className = 'color-slider-block';
    
    const header = document.createElement('div');
    header.className = 'slider-header';
    header.innerHTML = `<span>${title}</span><span id="val-${id}" class="slider-val">${val}${suffix}</span>`;
    block.appendChild(header);

    const input = document.createElement('input');
    input.type = 'range';
    input.id = id;
    input.min = min;
    input.max = max;
    input.value = val;
    input.addEventListener('input', (e) => {
      const v = parseInt(e.target.value, 10);
      document.getElementById(`val-${id}`).textContent = `${v}${suffix}`;
      onChange(v);
    });
    block.appendChild(input);
    return block;
  }

  // 3. Build Presets & Swatches
  const presetsContainer = document.getElementById('presets-container');
  presetsContainer.innerHTML = '';
  const presetConfigs = [
    { name: '👤 Naked Template Base', vals: {} },
    { name: '🧥 Cozy Clothes Set', vals: {} },
    { name: '🩱 Minimalist / Swimwear Base', vals: { legwear: 'none' } },
    { name: '🎉 Mix & Match Casual', vals: { legwear: 'none', topwear: 'clothing', bottomwear: 'clothing' } }
  ];

  presetConfigs.forEach((pc, idx) => {
    const btn = document.createElement('button');
    btn.className = idx === 0 ? 'action-btn' : 'action-btn secondary';
    btn.textContent = pc.name;
    btn.addEventListener('click', () => {
      Object.keys(DOLL_CONFIG.wardrobe).forEach(slot => {
        let val = 'skin_wear';
        if (pc.name.includes('Cozy') && DOLL_CONFIG.wardrobe[slot].options.some(o => o.value === 'clothing')) {
          val = 'clothing';
        }
        if (pc.vals[slot] !== undefined) {
          val = pc.vals[slot];
        }
        state.wardrobe[slot] = val;
        updateActiveOptionButton(slot, val);
      });
      renderDoll();
    });
    presetsContainer.appendChild(btn);
  });

  const swatchesContainer = document.getElementById('swatches-container');
  swatchesContainer.innerHTML = '';
  const swatches = [
    { color: '#ff4757', hue: 0, sat: 150, light: 100, name: 'Crimson Red' },
    { color: '#eccc68', hue: 45, sat: 130, light: 110, name: 'Blonde' },
    { color: '#2ed573', hue: 120, sat: 120, light: 100, name: 'Emerald' },
    { color: '#1e90ff', hue: 210, sat: 160, light: 100, name: 'Royal Blue' },
    { color: '#9b59b6', hue: 280, sat: 140, light: 100, name: 'Plum Purple' },
    { color: '#ff9f43', hue: 25, sat: 180, light: 100, name: 'Ginger Orange' },
    { color: '#a4b0be', hue: 0, sat: 0, light: 110, name: 'Silver Gray' },
    { color: '#2f3542', hue: 0, sat: 0, light: 40, name: 'Dark Raven' }
  ];

  swatches.forEach(sw => {
    const btn = document.createElement('button');
    btn.className = 'swatch-btn';
    btn.style.backgroundColor = sw.color;
    btn.title = sw.name;
    btn.addEventListener('click', () => {
      swatchesContainer.querySelectorAll('.swatch-btn').forEach(s => s.classList.remove('active'));
      btn.classList.add('active');

      state.dyes.hair.hue = sw.hue;
      state.dyes.hair.sat = sw.sat;
      state.dyes.hair.light = sw.light;

      if (document.getElementById('slide-hair-hue')) {
        document.getElementById('slide-hair-hue').value = sw.hue;
        document.getElementById('val-slide-hair-hue').textContent = `${sw.hue}°`;
      }
      if (document.getElementById('slide-hair-sat')) {
        document.getElementById('slide-hair-sat').value = sw.sat;
        document.getElementById('val-slide-hair-sat').textContent = `${sw.sat}%`;
      }
      if (document.getElementById('slide-hair-light')) {
        document.getElementById('slide-hair-light').value = sw.light;
        document.getElementById('val-slide-hair-light').textContent = `${sw.light}%`;
      }
      renderDoll();
    });
    swatchesContainer.appendChild(btn);
  });

  // 4. Build Calibration targets
  selectCalibrateLayer.innerHTML = '';
  const calibrateOptions = [{ value: 'clothed_assets', text: 'All Clothed Assets (Global)' }];
  
  const categoriesSeen = new Set();
  const subcategoriesSeen = new Set();
  DOLL_CONFIG.layers.forEach(layer => {
    if (layer.category) categoriesSeen.add(layer.category);
    if (layer.subcategory) subcategoriesSeen.add(layer.subcategory);
  });

  // Wardrobe slots first
  Object.keys(DOLL_CONFIG.wardrobe).forEach(slot => {
    calibrateOptions.push({ value: slot, text: `${slot.replace("wear", "wear").toUpperCase()} Layers` });
    subcategoriesSeen.delete(slot);
  });

  // Categories (excluding wardrobe which has individual slots)
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

function updateActiveOptionButton(slot, value) {
  const buttons = document.querySelectorAll(`[data-slot="${slot}"]`);
  buttons.forEach(btn => {
    btn.classList.toggle('active', btn.dataset.val === value);
  });
}

// Get the list of currently active layers based on selections
function getActiveLayers() {
  const active = [];

  DOLL_CONFIG.layers.forEach(layer => {
    if (layer.category === 'wardrobe') {
      const slot = layer.subcategory;
      const activeOptionVal = state.wardrobe[slot];
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

  // Adjust handwear drawing depth override
  const mapped = active.map(l => {
    let finalZ = l.z;
    if (l.subcategory === 'handwear') {
      const isClothing = l.optionValue !== 'skin_wear';
      const isRight = l.id.endsWith('_r') || l.id.endsWith('_right') || l.name.toLowerCase().endsWith('_r') || l.name.toLowerCase().endsWith('_right') || l.id.includes('_r_') || l.id.includes('_right_');
      const isLeft = l.id.endsWith('_l') || l.id.endsWith('_left') || l.name.toLowerCase().endsWith('_l') || l.name.toLowerCase().endsWith('_left') || l.id.includes('_l_') || l.id.includes('_left_');
      
      if (isRight) {
        finalZ = isClothing ? 15 : 14;
      } else if (isLeft) {
        finalZ = isClothing ? 260 : 259;
      } else if (state.wardrobeDepth['handwear']) {
        const depth = state.wardrobeDepth['handwear'];
        if (depth === 'behind') {
          finalZ = isClothing ? 15 : 14;
        } else if (depth === 'front_body') {
          finalZ = isClothing ? 165 : 164;
        } else if (depth === 'front_clothes') {
          finalZ = isClothing ? 260 : 259;
        }
      }
    }
    return { ...l, computedZ: finalZ };
  });

  return mapped.sort((a, b) => a.computedZ - b.computedZ);
}

// Render composite elements
function renderDoll() {
  targetContainer.innerHTML = '';
  const activeLayers = getActiveLayers();

  activeLayers.forEach(layer => {
    const img = document.createElement('img');
    img.src = localImageCache[layer.file] || `public/assets/${layer.file}`;
    img.alt = layer.id;
    img.className = 'doll-layer-img';
    img.style.zIndex = layer.computedZ;

    let x = 0;
    let y = 0;

    // Apply global clothed assets calibration offset
    if (layer.file.startsWith('clothing_')) {
      x += state.offsets.clothed_assets.x;
      y += state.offsets.clothed_assets.y;
    }

    // Apply specific category offsets
    if (layer.category && state.offsets[layer.category]) {
      x += state.offsets[layer.category].x;
      y += state.offsets[layer.category].y;
    }

    // Apply specific subcategory offsets (override/stack)
    if (layer.subcategory && state.offsets[layer.subcategory] && layer.subcategory !== layer.category) {
      x += state.offsets[layer.subcategory].x;
      y += state.offsets[layer.subcategory].y;
    }

    // Apply color filters
    let filters = '';
    if (layer.dyeable) {
      if (layer.category === 'hair') {
        filters = `hue-rotate(${state.dyes.hair.hue}deg) saturate(${state.dyes.hair.sat}%) brightness(${state.dyes.hair.light}%)`;
      } else if (layer.subcategory === 'irides') {
        filters = `hue-rotate(${state.dyes.eyes.hue}deg) saturate(130%)`;
      }
    }

    img.style.transform = `translate(${x}px, ${y}px)`;
    if (filters) {
      img.style.filter = filters;
    }

    targetContainer.appendChild(img);
  });
}

// Tab Switching
document.querySelectorAll('.tab-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.tab-pane').forEach(p => p.classList.remove('active'));
    
    btn.classList.add('active');
    const tabId = `tab-${btn.dataset.tab}`;
    document.getElementById(tabId).classList.add('active');
  });
});

// Viewport Actions
document.getElementById('btn-zoom-in').addEventListener('click', () => {
  state.zoom = Math.min(state.zoom + 0.15, 2.5);
  updateViewportTransform();
});
document.getElementById('btn-zoom-out').addEventListener('click', () => {
  state.zoom = Math.max(state.zoom - 0.15, 0.5);
  updateViewportTransform();
});
document.getElementById('btn-reset-view').addEventListener('click', () => {
  state.zoom = 1.0;
  updateViewportTransform();
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

function updateViewportTransform() {
  dollContainer.style.transform = `scale(${state.zoom})`;
}

// Alignment calibration utilities
let isCalibrationTabActive = false;
document.querySelectorAll('.tab-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    isCalibrationTabActive = (btn.dataset.tab === 'calibration');
    if (isCalibrationTabActive) {
      updateCalibrateUI();
    }
  });
});

function getSelectedCalibrateGroup() {
  return selectCalibrateLayer.value;
}

function updateCalibrateUI() {
  const group = getSelectedCalibrateGroup();
  if (!group) return;
  const offset = state.offsets[group] || { x: 0, y: 0 };
  valCalibrateX.textContent = `${offset.x}px`;
  valCalibrateY.textContent = `${offset.y}px`;
  txtCalibrationCode.value = JSON.stringify(state.offsets, null, 2);
}

function adjustOffset(dx, dy) {
  const group = getSelectedCalibrateGroup();
  if (!group) return;
  if (!state.offsets[group]) state.offsets[group] = { x: 0, y: 0 };
  state.offsets[group].x += dx;
  state.offsets[group].y += dy;
  updateCalibrateUI();
  renderDoll();
}

// Wire DPAD
dpadUp.addEventListener('click', (e) => adjustOffset(0, -1 * (e.shiftKey ? 5 : 1)));
dpadDown.addEventListener('click', (e) => adjustOffset(0, 1 * (e.shiftKey ? 5 : 1)));
dpadLeft.addEventListener('click', (e) => adjustOffset(-1 * (e.shiftKey ? 5 : 1), 0));
dpadRight.addEventListener('click', (e) => adjustOffset(1 * (e.shiftKey ? 5 : 1), 0));

btnCalibrateResetLayer.addEventListener('click', () => {
  const group = getSelectedCalibrateGroup();
  if (group) {
    state.offsets[group] = { x: 0, y: 0 };
    updateCalibrateUI();
    renderDoll();
  }
});

btnCalibrateResetAll.addEventListener('click', () => {
  Object.keys(state.offsets).forEach(k => {
    state.offsets[k] = { x: 0, y: 0 };
  });
  updateCalibrateUI();
  renderDoll();
});

// Keyboard controls
window.addEventListener('keydown', (e) => {
  if (!isCalibrationTabActive) return;
  const step = e.shiftKey ? 5 : 1;
  if (e.key === 'ArrowUp') {
    e.preventDefault();
    adjustOffset(0, -step);
  } else if (e.key === 'ArrowDown') {
    e.preventDefault();
    adjustOffset(0, step);
  } else if (e.key === 'ArrowLeft') {
    e.preventDefault();
    adjustOffset(-step, 0);
  } else if (e.key === 'ArrowRight') {
    e.preventDefault();
    adjustOffset(step, 0);
  }
});

selectCalibrateLayer.addEventListener('change', updateCalibrateUI);

btnCopyCalibration.addEventListener('click', () => {
  navigator.clipboard.writeText(txtCalibrationCode.value)
    .then(() => {
      const originalText = btnCopyCalibration.textContent;
      btnCopyCalibration.textContent = '📋 Copied!';
      btnCopyCalibration.style.borderColor = 'var(--success-color)';
      btnCopyCalibration.style.color = 'var(--success-color)';
      setTimeout(() => {
        btnCopyCalibration.textContent = originalText;
        btnCopyCalibration.style.borderColor = '';
        btnCopyCalibration.style.color = '';
      }, 1500);
    })
    .catch(err => {
      console.error('Failed to copy config: ', err);
    });
});

// Design Operations
document.getElementById('btn-randomize').addEventListener('click', () => {
  // Randomize wardrobe
  Object.entries(DOLL_CONFIG.wardrobe).forEach(([slot, config]) => {
    const values = config.options.map(o => o.value);
    const randVal = values[Math.floor(Math.random() * values.length)];
    state.wardrobe[slot] = randVal;
    updateActiveOptionButton(slot, randVal);
  });

  // Randomize dyes
  const hairDyeable = DOLL_CONFIG.layers.some(l => l.category === 'hair' && l.dyeable);
  const eyesDyeable = DOLL_CONFIG.layers.some(l => l.subcategory === 'irides' && l.dyeable);

  if (hairDyeable) {
    state.dyes.hair.hue = Math.floor(Math.random() * 360);
    state.dyes.hair.sat = Math.floor(Math.random() * 150) + 50;
    state.dyes.hair.light = Math.floor(Math.random() * 100) + 50;

    if (document.getElementById('slide-hair-hue')) {
      document.getElementById('slide-hair-hue').value = state.dyes.hair.hue;
      document.getElementById('val-slide-hair-hue').textContent = `${state.dyes.hair.hue}°`;
    }
    if (document.getElementById('slide-hair-sat')) {
      document.getElementById('slide-hair-sat').value = state.dyes.hair.sat;
      document.getElementById('val-slide-hair-sat').textContent = `${state.dyes.hair.sat}%`;
    }
    if (document.getElementById('slide-hair-light')) {
      document.getElementById('slide-hair-light').value = state.dyes.hair.light;
      document.getElementById('val-slide-hair-light').textContent = `${state.dyes.hair.light}%`;
    }
  }

  if (eyesDyeable) {
    state.dyes.eyes.hue = Math.floor(Math.random() * 360);
    if (document.getElementById('slide-eye-hue')) {
      document.getElementById('slide-eye-hue').value = state.dyes.eyes.hue;
      document.getElementById('val-slide-eye-hue').textContent = `${state.dyes.eyes.hue}°`;
    }
  }

  renderDoll();
});

document.getElementById('btn-reset').addEventListener('click', () => {
  // Revert wardrobe
  Object.entries(DOLL_CONFIG.wardrobe).forEach(([slot, config]) => {
    state.wardrobe[slot] = config.defaultValue;
    updateActiveOptionButton(slot, config.defaultValue);
  });

  // Revert depth
  if (DOLL_CONFIG.wardrobe.handwear) {
    state.wardrobeDepth['handwear'] = 'front_body';
    const el = document.getElementById('select-handwear-depth');
    if (el) el.value = 'front_body';
  }

  // Revert toggles
  Object.keys(state.toggles).forEach(k => {
    state.toggles[k] = true;
    const el = document.getElementById(`toggle-${k}`);
    if (el) el.checked = true;
  });

  // Revert dyes
  state.dyes.hair.hue = 0;
  state.dyes.hair.sat = 100;
  state.dyes.hair.light = 100;
  state.dyes.eyes.hue = 0;

  ['slide-hair-hue', 'slide-hair-sat', 'slide-hair-light', 'slide-eye-hue'].forEach(id => {
    const el = document.getElementById(id);
    if (el) {
      const isDyeValue = id.includes('sat') || id.includes('light');
      el.value = isDyeValue ? 100 : 0;
      const suffix = isDyeValue ? '%' : '°';
      document.getElementById(`val-${id}`).textContent = `${el.value}${suffix}`;
    }
  });

  document.querySelectorAll('.swatch-btn').forEach(sw => sw.classList.remove('active'));

  renderDoll();
});

// Helper to switch tabs
function switchToTab(tabName) {
  document.querySelectorAll('.tab-btn').forEach(b => {
    b.classList.toggle('active', b.dataset.tab === tabName);
  });
  document.querySelectorAll('.tab-pane').forEach(p => {
    p.classList.toggle('active', p.id === `tab-${tabName}`);
  });
}

// Bounding-box and PSD parsing keywords
const KEYWORDS = {
  hair: ['hair', 'bang', 'fringe', 'tail'],
  eyes: ['eye', 'iris', 'brow', 'lash', 'white'],
  face: ['face', 'neck', 'ears', 'nose', 'mouth', 'body', 'torso', 'skin', 'head'],
  wardrobe: ['wear', 'cloth', 'top', 'bottom', 'leg', 'hand', 'glove', 'pants', 'shirt', 'skirt', 'shoe', 'sock']
};

const WARDROBE_SLOTS = {
  topwear: ['top', 'shirt', 'jacket', 'vest', 'coat', 'chest'],
  bottomwear: ['bottom', 'skirt', 'underwear', 'waist'],
  legwear: ['leg', 'pant', 'sock', 'shoe', 'boot', 'foot', 'feet'],
  handwear: ['hand', 'glove', 'arm', 'sleeve']
};

function cleanLayerName(name) {
  return name.toLowerCase().trim().replace(/\s+/g, '_').replace(/-/g, '_');
}

function getCategory(cleanName) {
  if (KEYWORDS.wardrobe.some(w => cleanName.includes(w))) return 'wardrobe';
  if (KEYWORDS.hair.some(w => cleanName.includes(w))) return 'hair';
  if (KEYWORDS.eyes.some(w => cleanName.includes(w))) return 'eyes';
  return 'face';
}

function getWardrobeSlot(cleanName) {
  for (const [slot, kws] of Object.entries(WARDROBE_SLOTS)) {
    if (kws.some(kw => cleanName.includes(kw))) return slot;
  }
  return 'accessories';
}

function getOptionValue(cleanName, slot, psdFileName = null) {
  if (cleanName.includes('skin_wear') || cleanName.includes('naked') || cleanName === slot) return 'skin_wear';
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
      if (fnLower.includes('clothed') || fnLower.includes('clothing')) {
        return 'clothing';
      }
      if (fnLower.includes('naked') || fnLower.includes('skin')) {
        return 'skin_wear';
      }
    }
    
    // Fallback: check if cleanName matches slot or orientation suffixes
    if (cleanName === slot || 
        cleanName.endsWith('_l') || 
        cleanName.endsWith('_r') || 
        cleanName.endsWith('_left') || 
        cleanName.endsWith('_right')) {
      return 'skin_wear';
    }
    
    return 'default';
  }
  return val;
}

// Convert canvas to Blob
function canvasToBlob(canvas) {
  return new Promise(resolve => canvas.toBlob(resolve, 'image/png'));
}

// Image Loader
function loadImage(src) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.crossOrigin = 'anonymous';
    img.onload = () => resolve(img);
    img.onerror = () => reject(new Error('Failed to load image: ' + src));
    img.src = src;
  });
}

// Compute non-transparent bounding box
function getBoundingBox(canvas) {
  const ctx = canvas.getContext('2d');
  const imgData = ctx.getImageData(0, 0, canvas.width, canvas.height);
  const data = imgData.data;
  const width = canvas.width;
  const height = canvas.height;
  
  let minX = width, maxX = -1, minY = height, maxY = -1;
  
  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      const idx = (y * width + x) * 4;
      if (data[idx + 3] > 10) { // alpha > 10
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

// Apply Chroma Key filter to canvas
function applyChromaKey(canvas, keyColorHex, tolerance) {
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

// Client-side PSD ingestion
function loadAndParsePSD(file) {
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
      const psd = agPsd.readPsd(buffer);
      
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
      
      // ag-psd returns bottom-to-top order (matches the file format and psd_to_prototype.py).
      // No reversal is needed to assign correct incremental Z-indexes.
      
      if (rawLayers.length === 0) {
        throw new Error('No valid layer images found in the PSD file.');
      }
      
      // Clear previous cache
      Object.values(localImageCache).forEach(url => URL.revokeObjectURL(url));
      localImageCache = {};
      localBlobCache = {};
      
      const docWidth = psd.width || 768;
      const docHeight = psd.height || 768;
      
      const layersConfig = [];
      const wardrobeMapping = {};
      
      for (let idx = 0; idx < rawLayers.length; idx++) {
        const layer = rawLayers[idx];
        const cleanName = cleanLayerName(layer.name);
        const zIndex = (idx + 1) * 10;
        
        // Reconstruct layer onto full-sized document canvas
        const fullCanvas = document.createElement('canvas');
        fullCanvas.width = docWidth;
        fullCanvas.height = docHeight;
        const ctx = fullCanvas.getContext('2d');
        ctx.drawImage(layer.canvas, layer.left, layer.top);
        
        const blob = await canvasToBlob(fullCanvas);
        const filename = `${cleanName}.png`;
        const objectUrl = URL.createObjectURL(blob);
        
        localImageCache[filename] = objectUrl;
        localBlobCache[filename] = blob;
        
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
          wardrobeMapping[slot].layers.push({
            id: cleanName,
            optionValue: optVal
          });
        } else if (category === 'hair') {
          const subcat = (cleanName.includes('front') || cleanName.includes('bang') || cleanName.includes('fringe')) ? 'hair_front' : 'hair_back';
          layerMeta.subcategory = subcat;
          layerMeta.toggleable = true;
          layerMeta.defaultVisible = true;
          layerMeta.dyeable = true;
        } else if (category === 'eyes') {
          let subcat = 'eyes_other';
          if (cleanName.includes('white')) {
            subcat = 'eyewhite';
          } else if (cleanName.includes('iris') || cleanName.includes('iride')) {
            subcat = 'irides';
            layerMeta.dyeable = true;
          } else if (cleanName.includes('brow')) {
            subcat = 'eyebrows';
          } else if (cleanName.includes('lash')) {
            subcat = 'eyelashes';
          }
          layerMeta.subcategory = subcat;
          layerMeta.toggleable = true;
          layerMeta.defaultVisible = true;
        } else { // face
          let subcat = 'face';
          if (cleanName.includes('neck')) {
            subcat = 'neck';
          } else if (cleanName.includes('ears') || cleanName.includes('ear')) {
            subcat = 'ears';
            layerMeta.toggleable = true;
            layerMeta.defaultVisible = true;
          } else if (cleanName.includes('nose')) {
            subcat = 'nose';
            layerMeta.toggleable = true;
            layerMeta.defaultVisible = true;
          } else if (cleanName.includes('mouth')) {
            subcat = 'mouth';
            layerMeta.toggleable = true;
            layerMeta.defaultVisible = true;
          }
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
          const sortKey = (v) => {
            if (v === 'skin_wear') return 0;
            if (v === 'clothing') return 1;
            return 2;
          };
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
          
          optionsList.push({
            value: val,
            name: display_name,
            layers: final_layers
          });
        }
        
        optionsList.push({
          value: 'none',
          name: 'Invisible / None',
          layers: []
        });
        
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
      
      initializeState();
      buildUI();
      renderDoll();
      updateViewportTransform();
      updateCalibrateUI();
      
      psdProgressFill.style.width = '100%';
      txtPsdStatus.textContent = `PSD ${file.name} successfully imported!`;
      setTimeout(() => {
        psdStatus.style.display = 'none';
      }, 2500);
      
    } catch (err) {
      console.error(err);
      txtPsdStatus.textContent = `Error parsing PSD: ${err.message}`;
      psdProgressFill.style.backgroundColor = 'var(--danger-color)';
    }
  };
  
  reader.readAsArrayBuffer(file);
}

// Drag & Drop event bindings
function preventDefaults(e) {
  e.preventDefault();
  e.stopPropagation();
}

['dragenter', 'dragover', 'dragleave', 'drop'].forEach(name => {
  window.addEventListener(name, preventDefaults, false);
});

const dragDropOverlay = document.getElementById('drag-drop-overlay');

window.addEventListener('dragenter', (e) => {
  if (e.dataTransfer.types.includes('Files')) {
    dragDropOverlay.classList.add('active');
  }
});
window.addEventListener('dragover', (e) => {
  if (e.dataTransfer.types.includes('Files')) {
    dragDropOverlay.classList.add('active');
  }
});
dragDropOverlay.addEventListener('dragleave', (e) => {
  dragDropOverlay.classList.remove('active');
});
dragDropOverlay.addEventListener('drop', (e) => {
  dragDropOverlay.classList.remove('active');
  const files = e.dataTransfer.files;
  if (files && files.length > 0) {
    const file = files[0];
    if (file.name.endsWith('.psd')) {
      switchToTab('studio');
      loadAndParsePSD(file);
    } else if (file.type.startsWith('image/')) {
      switchToTab('studio');
      handleAssetFileSelect(file);
    }
  }
});

// File browse elements
const psdDropZone = document.getElementById('psd-drop-zone');
const inputPsd = document.getElementById('input-psd');
psdDropZone.addEventListener('click', () => inputPsd.click());
inputPsd.addEventListener('change', (e) => {
  if (e.target.files.length > 0) {
    loadAndParsePSD(e.target.files[0]);
  }
});

['dragenter', 'dragover'].forEach(name => {
  psdDropZone.addEventListener(name, () => psdDropZone.classList.add('dragover'));
});
['dragleave', 'drop'].forEach(name => {
  psdDropZone.addEventListener(name, () => psdDropZone.classList.remove('dragover'));
});
psdDropZone.addEventListener('drop', (e) => {
  if (e.dataTransfer.files.length > 0 && e.dataTransfer.files[0].name.endsWith('.psd')) {
    loadAndParsePSD(e.dataTransfer.files[0]);
  }
});

const assetDropZone = document.getElementById('asset-drop-zone');
const inputAsset = document.getElementById('input-asset');
const assetDropText = document.getElementById('asset-drop-text');
const txtIngestName = document.getElementById('txt-ingest-name');
const selectIngestSlot = document.getElementById('select-ingest-slot');
const btnIngestSubmit = document.getElementById('btn-ingest-submit');

assetDropZone.addEventListener('click', () => inputAsset.click());
inputAsset.addEventListener('change', (e) => {
  if (e.target.files.length > 0) {
    handleAssetFileSelect(e.target.files[0]);
  }
});

['dragenter', 'dragover'].forEach(name => {
  assetDropZone.addEventListener(name, () => assetDropZone.classList.add('dragover'));
});
['dragleave', 'drop'].forEach(name => {
  assetDropZone.addEventListener(name, () => assetDropZone.classList.remove('dragover'));
});
assetDropZone.addEventListener('drop', (e) => {
  if (e.dataTransfer.files.length > 0 && e.dataTransfer.files[0].type.startsWith('image/')) {
    handleAssetFileSelect(e.dataTransfer.files[0]);
  }
});

function handleAssetFileSelect(file) {
  pendingAssetFile = file;
  assetDropText.textContent = `Selected: ${file.name}`;
  
  if (!txtIngestName.value) {
    const baseName = file.name.replace(/\.[^/.]+$/, "").replace(/_/g, ' ').replace(/-/g, ' ');
    txtIngestName.value = baseName.replace(/\b\w/g, c => c.toUpperCase());
  }
  
  btnIngestSubmit.removeAttribute('disabled');
}

// ML AI background removal trigger
document.getElementById('btn-ml-bg').addEventListener('click', async () => {
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
    pendingAssetFile = new File([processedBlob], pendingAssetFile.name, { type: 'image/png' });
    assetDropText.textContent = `Processed with AI: ${pendingAssetFile.name}`;
    txtMlStatus.textContent = 'Background removed successfully!';
    setTimeout(() => {
      mlStatus.style.display = 'none';
    }, 1500);
  } catch (err) {
    console.error(err);
    txtMlStatus.textContent = `Error: ${err.message}`;
  }
});

// Process and submit wardrobe asset
btnIngestSubmit.addEventListener('click', async () => {
  if (!pendingAssetFile) return;
  
  const slot = selectIngestSlot.value;
  const displayName = txtIngestName.value.trim() || 'Custom Option';
  const cleanName = `${slot}_${displayName.toLowerCase().replace(/\s+/g, '_').replace(/[^a-z0-9_]/g, '')}`;
  const filename = `${cleanName}.png`;
  
  btnIngestSubmit.setAttribute('disabled', 'true');
  btnIngestSubmit.textContent = 'Processing asset...';
  
  try {
    const fileUrl = URL.createObjectURL(pendingAssetFile);
    const originalImg = await loadImage(fileUrl);
    
    const origCanvas = document.createElement('canvas');
    origCanvas.width = originalImg.width;
    origCanvas.height = originalImg.height;
    const origCtx = origCanvas.getContext('2d');
    origCtx.drawImage(originalImg, 0, 0);
    
    // Apply Chroma Key
    if (document.getElementById('chk-chromakey').checked) {
      const keyColor = document.getElementById('color-chromakey').value;
      const tolerance = parseInt(document.getElementById('range-chromakey').value, 10);
      applyChromaKey(origCanvas, keyColor, tolerance);
    }
    
    const docWidth = DOLL_CONFIG.canvas.width;
    const docHeight = DOLL_CONFIG.canvas.height;
    
    let targetX = 0, targetY = 0;
    let targetWidth = docWidth, targetHeight = docHeight;
    let isAlreadyAligned = (originalImg.width === docWidth && originalImg.height === docHeight);
    
    let clothCropCanvas = null;
    
    if (!isAlreadyAligned) {
      const clothBox = getBoundingBox(origCanvas);
      if (clothBox) {
        clothCropCanvas = document.createElement('canvas');
        clothCropCanvas.width = clothBox.width;
        clothCropCanvas.height = clothBox.height;
        const cropCtx = clothCropCanvas.getContext('2d');
        cropCtx.drawImage(origCanvas, clothBox.x, clothBox.y, clothBox.width, clothBox.height, 0, 0, clothBox.width, clothBox.height);
        
        let baseLayer = DOLL_CONFIG.layers.find(l => 
          l.category === 'wardrobe' && 
          l.subcategory === slot && 
          l.optionValue === 'skin_wear'
        );
        if (!baseLayer) {
          baseLayer = DOLL_CONFIG.layers.find(l => 
            l.category === 'wardrobe' && 
            l.subcategory === slot
          );
        }
        
        let baseBox = null;
        if (baseLayer) {
          const baseImgSrc = localImageCache[baseLayer.file] || `public/assets/${baseLayer.file}`;
          const baseImg = await loadImage(baseImgSrc);
          const baseCanvas = document.createElement('canvas');
          baseCanvas.width = baseImg.width;
          baseCanvas.height = baseImg.height;
          const baseCtx = baseCanvas.getContext('2d');
          baseCtx.drawImage(baseImg, 0, 0);
          baseBox = getBoundingBox(baseCanvas);
        }
        
        if (baseBox) {
          const scaleX = baseBox.width / clothBox.width;
          const scaleY = baseBox.height / clothBox.height;
          const scale = Math.min(scaleX, scaleY);
          
          targetWidth = clothBox.width * scale;
          targetHeight = clothBox.height * scale;
          targetX = baseBox.x + (baseBox.width - targetWidth) / 2;
          targetY = baseBox.y + (baseBox.height - targetHeight) / 2;
        } else {
          const scale = Math.min(docWidth / clothBox.width, docHeight / clothBox.height) * 0.6;
          targetWidth = clothBox.width * scale;
          targetHeight = clothBox.height * scale;
          targetX = (docWidth - targetWidth) / 2;
          targetY = (docHeight - targetHeight) / 2;
        }
      }
    }
    
    const finalDocCanvas = document.createElement('canvas');
    finalDocCanvas.width = docWidth;
    finalDocCanvas.height = docHeight;
    const finalDocCtx = finalDocCanvas.getContext('2d');
    
    if (isAlreadyAligned) {
      finalDocCtx.drawImage(origCanvas, 0, 0);
    } else if (clothCropCanvas) {
      finalDocCtx.drawImage(
        clothCropCanvas,
        0, 0, clothCropCanvas.width, clothCropCanvas.height,
        targetX, targetY, targetWidth, targetHeight
      );
    } else {
      finalDocCtx.drawImage(origCanvas, 0, 0);
    }
    
    const finalBlob = await canvasToBlob(finalDocCanvas);
    const finalObjectUrl = URL.createObjectURL(finalBlob);
    
    localImageCache[filename] = finalObjectUrl;
    localBlobCache[filename] = finalBlob;
    
    const wardrobeLayers = DOLL_CONFIG.layers.filter(l => l.category === 'wardrobe');
    const maxZ = wardrobeLayers.reduce((max, l) => Math.max(max, l.z), 200);
    const newZ = maxZ + 10;
    
    const newLayer = {
      id: cleanName,
      name: displayName,
      file: filename,
      z: newZ,
      category: 'wardrobe',
      subcategory: slot,
      optionValue: cleanName
    };
    
    DOLL_CONFIG.layers.push(newLayer);
    
    const slotConfig = DOLL_CONFIG.wardrobe[slot];
    if (slotConfig) {
      const skinWearOption = slotConfig.options.find(o => o.value === 'skin_wear');
      const skinWearLayers = skinWearOption ? skinWearOption.layers : [];
      
      slotConfig.options.push({
        value: cleanName,
        name: displayName,
        layers: [...skinWearLayers, cleanName]
      });
    }
    
    state.wardrobe[slot] = cleanName;
    
    buildUI();
    renderDoll();
    updateCalibrateUI();
    
    pendingAssetFile = null;
    pendingAssetImage = null;
    txtIngestName.value = '';
    assetDropText.textContent = 'Drag & drop PNG/JPG image here, or click to browse';
    inputAsset.value = '';
    
    alert(`Successfully processed and added "${displayName}" to wardrobe!`);
  } catch (err) {
    console.error(err);
    alert(`Error ingesting asset: ${err.message}`);
  } finally {
    btnIngestSubmit.removeAttribute('disabled');
    btnIngestSubmit.textContent = 'Process & Add to Wardrobe';
  }
});

// Serialize config
function generateConfigJSString() {
  if (!DOLL_CONFIG.defaults) DOLL_CONFIG.defaults = {};
  DOLL_CONFIG.defaults.offsets = state.offsets;
  
  return `// Dynamic Paper Doll Studio Configuration
// Automatically generated by Paper Doll Studio Client

const DOLL_CONFIG = ${JSON.stringify(DOLL_CONFIG, null, 2)};
`;
}

function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

// Download single config file
document.getElementById('btn-download-config').addEventListener('click', () => {
  const configStr = generateConfigJSString();
  const blob = new Blob([configStr], { type: 'application/javascript;charset=utf-8' });
  downloadBlob(blob, 'doll_config.js');
});

// Export ZIP archive
document.getElementById('btn-export-zip').addEventListener('click', async () => {
  const btn = document.getElementById('btn-export-zip');
  const origText = btn.textContent;
  btn.setAttribute('disabled', 'true');
  btn.textContent = 'Creating ZIP package...';
  
  try {
    const zip = new JSZip();
    
    // Config js
    zip.file('doll_config.js', generateConfigJSString());
    
    // Readme or instructions
    zip.file('README.md', `# Paper Doll Studio Exported Project
    
Unzip this package into your game's web asset directory. It contains:
- \`doll_config.js\`: Character layer layout, customization slots, and calibration offsets.
- \`public/assets/\`: All extracted and generated PNG assets.
- App files (index.html, style.css, app.js): You can open \`index.html\` directly in a browser to run this character customizing application!
`);
    
    const assetsFolder = zip.folder('public/assets');
    
    // Add all active and cached images
    for (const layer of DOLL_CONFIG.layers) {
      const filename = layer.file;
      if (localBlobCache[filename]) {
        assetsFolder.file(filename, localBlobCache[filename]);
      } else {
        try {
          const response = await fetch(`public/assets/${filename}`);
          if (response.ok) {
            const blob = await response.blob();
            assetsFolder.file(filename, blob);
          } else {
            console.warn(`Could not fetch public/assets/${filename} from server.`);
          }
        } catch (err) {
          console.error(`Error fetching asset ${filename}:`, err);
        }
      }
    }
    
    // Fetch and include core client files (HTML, CSS, JS) for full portability
    try {
      const indexRes = await fetch('index.html');
      if (indexRes.ok) zip.file('index.html', await indexRes.blob());
      
      const styleRes = await fetch('style.css');
      if (styleRes.ok) zip.file('style.css', await styleRes.blob());
      
      const appRes = await fetch('app.js');
      if (appRes.ok) zip.file('app.js', await appRes.blob());
    } catch (err) {
      console.warn('Could not include core app files in ZIP:', err);
    }
    
    const zipContent = await zip.generateAsync({ type: 'blob' });
    downloadBlob(zipContent, 'paperdoll_project.zip');
    
  } catch (err) {
    console.error(err);
    alert(`Failed to export ZIP package: ${err.message}`);
  } finally {
    btn.removeAttribute('disabled');
    btn.textContent = origText;
  }
});

// App Startup
initializeState();
buildUI();
renderDoll();
updateViewportTransform();
updateCalibrateUI();
