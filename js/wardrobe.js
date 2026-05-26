import { state, DOLL_CONFIG, TOGGLE_GROUPS, getActiveLayers, pushHistory } from './state.js';
import { renderDoll } from './render.js';

export function updateActiveOptionButton(slot, value) {
  const buttons = document.querySelectorAll(`[data-slot="${slot}"]`);
  buttons.forEach(btn => {
    btn.classList.toggle('active', btn.dataset.val === value);
  });
  const select = document.querySelector(`[data-wardrobe-select="${slot}"]`);
  if (select) select.value = value;
  const swatch = document.querySelector(`[data-wardrobe-swatch="${slot}"]`);
  const slotConfig = DOLL_CONFIG.wardrobe[slot];
  const selected = slotConfig?.options.find(opt => opt.value === value);
  if (swatch) swatch.className = `option-preview wardrobe-slot-swatch ${optionPreviewClass(slot, selected)}`;
}

function optionPreviewClass(slot, opt) {
  if (!opt || opt.value === 'none') return 'none-bg';
  if (opt.value === 'skin_wear') return 'skin-bg';
  if (opt.value !== 'clothing') return 'cloth-generic-bg';
  if (slot === 'topwear') return 'cloth-top-bg';
  if (slot === 'dress') return 'cloth-dress-bg';
  if (slot === 'bottomwear') return 'cloth-bot-bg';
  if (slot === 'legwear') return 'cloth-leg-bg';
  if (slot === 'handwear') return 'cloth-hand-bg';
  if (slot === 'outerwear') return 'cloth-outerwear-bg';
  if (slot === 'skirt') return 'cloth-skirt-bg';
  if (slot === 'pants') return 'cloth-pants-bg';
  return 'cloth-generic-bg';
}

export function buildUI(targetContainer) {
  const wardrobeContainer = document.getElementById('wardrobe-options-container');
  wardrobeContainer.innerHTML = '';

  const wardrobeGroup = document.createElement('div');
  wardrobeGroup.className = 'control-group wardrobe-compact-group';
  const wardrobeTitle = document.createElement('h3');
  wardrobeTitle.textContent = 'Wardrobe Slots';
  wardrobeGroup.appendChild(wardrobeTitle);

  const slotList = document.createElement('div');
  slotList.className = 'wardrobe-slot-list';

  Object.entries(DOLL_CONFIG.wardrobe).forEach(([slot, slotConfig]) => {
    const row = document.createElement('div');
    row.className = 'wardrobe-slot-row';

    const label = document.createElement('label');
    label.className = 'wardrobe-slot-label';
    label.htmlFor = `select-wardrobe-${slot}`;
    label.textContent = slotConfig.name || slot.replace(/_/g, ' ');
    row.appendChild(label);

    const current = slotConfig.options.find(opt => opt.value === state.wardrobe[slot]) || slotConfig.options[0];
    const swatch = document.createElement('span');
    swatch.className = `option-preview wardrobe-slot-swatch ${optionPreviewClass(slot, current)}`;
    swatch.dataset.wardrobeSwatch = slot;
    row.appendChild(swatch);

    const select = document.createElement('select');
    select.id = `select-wardrobe-${slot}`;
    select.className = 'wardrobe-slot-select';
    select.dataset.wardrobeSelect = slot;
    slotConfig.options.forEach(opt => {
      const optEl = document.createElement('option');
      optEl.value = opt.value;
      optEl.textContent = opt.name;
      if (opt.value === state.wardrobe[slot]) optEl.selected = true;
      select.appendChild(optEl);
    });

    select.addEventListener('change', () => {
      pushHistory();
      state.wardrobe[slot] = select.value;

      if (slot === 'dress' && select.value === 'clothing') {
        state.wardrobe.topwear = 'skin_wear';
        state.wardrobe.bottomwear = 'skin_wear';
        updateActiveOptionButton('topwear', 'skin_wear');
        updateActiveOptionButton('bottomwear', 'skin_wear');
      }

      const selected = slotConfig.options.find(opt => opt.value === state.wardrobe[slot]);
      swatch.className = `option-preview wardrobe-slot-swatch ${optionPreviewClass(slot, selected)}`;
      renderWardrobeLayerStack(targetContainer);
      renderDoll(targetContainer);
    });

    row.appendChild(select);
    slotList.appendChild(row);
  });

  wardrobeGroup.appendChild(slotList);
  wardrobeContainer.appendChild(wardrobeGroup);

  const depthContainer = document.getElementById('depth-controls-container');
  if (depthContainer) depthContainer.innerHTML = '';

  renderWardrobeLayerStack(targetContainer);

  // Appearance toggles
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
      pushHistory();
      state.toggles[groupId] = e.target.checked;
      renderDoll(targetContainer);
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

  // Dye sliders
  const slidersContainer = document.getElementById('dye-sliders-container');
  slidersContainer.innerHTML = '';

  const dyeGroup = document.createElement('div');
  dyeGroup.className = 'control-group';
  dyeGroup.innerHTML = '<h3>Dynamic Dye Colors</h3><p class="group-desc">Apply CSS real-time filter adjustments to customize colors.</p>';

  const hairDyeable = DOLL_CONFIG.layers.some(l => l.category === 'hair' && l.dyeable);
  const eyesDyeable = DOLL_CONFIG.layers.some(l => l.subcategory === 'irides' && l.dyeable);

  if (hairDyeable) {
    dyeGroup.appendChild(createSliderBlock('Hair Hue', 'slide-hair-hue', 0, 360, state.dyes.hair.hue, '\u00b0', (val) => {
      pushHistory();
      state.dyes.hair.hue = val;
      renderDoll(targetContainer);
    }));
    dyeGroup.appendChild(createSliderBlock('Hair Saturation', 'slide-hair-sat', 0, 250, state.dyes.hair.sat, '%', (val) => {
      pushHistory();
      state.dyes.hair.sat = val;
      renderDoll(targetContainer);
    }));
    dyeGroup.appendChild(createSliderBlock('Hair Brightness', 'slide-hair-light', 20, 200, state.dyes.hair.light, '%', (val) => {
      pushHistory();
      state.dyes.hair.light = val;
      renderDoll(targetContainer);
    }));
  }

  if (eyesDyeable) {
    if (hairDyeable) {
      const div = document.createElement('div');
      div.className = 'divider';
      dyeGroup.appendChild(div);
    }
    dyeGroup.appendChild(createSliderBlock('Eye Color (Irides Hue)', 'slide-eye-hue', 0, 360, state.dyes.eyes.hue, '\u00b0', (val) => {
      pushHistory();
      state.dyes.eyes.hue = val;
      renderDoll(targetContainer);
    }));
  }

  if (hairDyeable || eyesDyeable) {
    slidersContainer.appendChild(dyeGroup);
  }

  // Presets
  const presetsContainer = document.getElementById('presets-container');
  presetsContainer.innerHTML = '';
  const presetConfigs = [
    { name: 'Naked Template Base', vals: {} },
    { name: 'Cozy Clothes Set', vals: {} },
    { name: 'Minimalist / Swimwear Base', vals: { legwear: 'none' } },
    { name: 'One-Piece Dress', vals: { dress: 'clothing', topwear: 'skin_wear', bottomwear: 'skin_wear' } },
    { name: 'Mix & Match Casual', vals: { legwear: 'none', topwear: 'clothing', bottomwear: 'clothing' } }
  ];

  presetConfigs.forEach((pc, idx) => {
    const btn = document.createElement('button');
    btn.className = idx === 0 ? 'action-btn' : 'action-btn secondary';
    btn.textContent = pc.name;
    btn.addEventListener('click', () => {
      pushHistory();
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
      renderDoll(targetContainer);
    });
    presetsContainer.appendChild(btn);
  });

  // Swatches
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
      pushHistory();
      swatchesContainer.querySelectorAll('.swatch-btn').forEach(s => s.classList.remove('active'));
      btn.classList.add('active');

      state.dyes.hair.hue = sw.hue;
      state.dyes.hair.sat = sw.sat;
      state.dyes.hair.light = sw.light;

      if (document.getElementById('slide-hair-hue')) {
        document.getElementById('slide-hair-hue').value = sw.hue;
        document.getElementById('val-slide-hair-hue').textContent = `${sw.hue}\u00b0`;
      }
      if (document.getElementById('slide-hair-sat')) {
        document.getElementById('slide-hair-sat').value = sw.sat;
        document.getElementById('val-slide-hair-sat').textContent = `${sw.sat}%`;
      }
      if (document.getElementById('slide-hair-light')) {
        document.getElementById('slide-hair-light').value = sw.light;
        document.getElementById('val-slide-hair-light').textContent = `${sw.light}%`;
      }
      renderDoll(targetContainer);
    });
    swatchesContainer.appendChild(btn);
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

function displayLayerName(layer) {
  return state.layerControls[layer.id]?.customName || layer.name || layer.id;
}

function slotLabel(slot) {
  return DOLL_CONFIG.wardrobe[slot]?.name || slot.replace(/_/g, ' ');
}

function baseComputedZ(layer) {
  return (layer.computedZ ?? layer.z ?? 0) - (state.layerControls[layer.id]?.zOffset || 0);
}

function isLayerInActiveWardrobeOption(layer) {
  if (layer.category !== 'wardrobe') return true;
  const slotConfig = DOLL_CONFIG.wardrobe[layer.subcategory];
  const selected = slotConfig?.options.find(o => o.value === state.wardrobe[layer.subcategory]);
  return !!selected?.layers.includes(layer.id);
}

function reorderWardrobeLayer(draggedId, targetId, targetContainer) {
  if (!draggedId || !targetId || draggedId === targetId) return;
  const rows = layerManagerRows();
  const from = rows.findIndex(layer => layer.id === draggedId);
  const to = rows.findIndex(layer => layer.id === targetId);
  if (from < 0 || to < 0) return;

  const zSlots = rows.map(layer => layer.computedZ);
  const nextRows = [...rows];
  const [dragged] = nextRows.splice(from, 1);
  nextRows.splice(to, 0, dragged);

  pushHistory();
  nextRows.forEach((layer, idx) => {
    const controls = ensureLayerControls(layer.id);
    controls.zOffset = Math.max(-9999, Math.min(9999, zSlots[idx] - baseComputedZ(layer)));
  });
  renderWardrobeLayerStack(targetContainer);
  renderDoll(targetContainer);
}

function layerManagerRows() {
  const activeIds = new Set(getActiveLayers().map(l => l.id));
  return DOLL_CONFIG.layers.map(layer => {
    const controls = state.layerControls[layer.id] || {};
    return {
      ...layer,
      name: controls.customName || layer.name,
      computedZ: layer.z + (controls.zOffset || 0),
      opacity: controls.opacity ?? 100,
      isActiveLayer: activeIds.has(layer.id),
    };
  }).sort((a, b) => b.computedZ - a.computedZ);
}

function uniqueLayerId(baseId) {
  let idx = 1;
  let id = `${baseId}_copy`;
  const ids = new Set(DOLL_CONFIG.layers.map(layer => layer.id));
  while (ids.has(id)) {
    idx++;
    id = `${baseId}_copy_${idx}`;
  }
  return id;
}

function duplicateLayer(layer, targetContainer) {
  const source = DOLL_CONFIG.layers.find(l => l.id === layer.id);
  if (!source) return;
  pushHistory();
  const copyId = uniqueLayerId(source.id);
  const copyName = `${displayLayerName(source)} Copy`;
  const clone = {
    ...source,
    id: copyId,
    name: copyName,
    z: (source.z || 0) + 1,
  };
  DOLL_CONFIG.layers.push(clone);
  state.layerControls[copyId] = {
    visible: true,
    opacity: state.layerControls[source.id]?.opacity ?? 100,
    zOffset: state.layerControls[source.id]?.zOffset || 0,
    customName: copyName,
  };

  if (source.category === 'wardrobe') {
    const slotConfig = DOLL_CONFIG.wardrobe[source.subcategory];
    const option = slotConfig?.options.find(o => o.value === state.wardrobe[source.subcategory])
      || slotConfig?.options.find(o => o.layers.includes(source.id));
    if (option && !option.layers.includes(copyId)) {
      const sourceIdx = option.layers.indexOf(source.id);
      option.layers.splice(sourceIdx >= 0 ? sourceIdx + 1 : option.layers.length, 0, copyId);
    }
  }

  renderWardrobeLayerStack(targetContainer);
  renderDoll(targetContainer);
}

function deleteLayer(layer, targetContainer) {
  const source = DOLL_CONFIG.layers.find(l => l.id === layer.id);
  if (!source) return;
  const ok = window.confirm(`Delete layer "${displayLayerName(source)}" from the current project config?`);
  if (!ok) return;
  pushHistory();
  DOLL_CONFIG.layers = DOLL_CONFIG.layers.filter(l => l.id !== source.id);
  delete state.layerControls[source.id];
  Object.values(DOLL_CONFIG.wardrobe).forEach(slotConfig => {
    slotConfig.options.forEach(option => {
      option.layers = option.layers.filter(id => id !== source.id);
    });
  });
  renderWardrobeLayerStack(targetContainer);
  renderDoll(targetContainer);
}

function renderWardrobeLayerStack(targetContainer) {
  const layerContainer = document.getElementById('layer-manager-container') || document.getElementById('depth-controls-container');
  if (!layerContainer) return;

  let panel = document.getElementById('wardrobe-layer-stack-panel');
  if (!panel) {
    panel = document.createElement('div');
    panel.id = 'wardrobe-layer-stack-panel';
    panel.className = 'control-group wardrobe-layer-stack layer-manager-editor';
    layerContainer.appendChild(panel);
  }

  panel.textContent = '';
  const title = document.createElement('h3');
  title.textContent = 'Layer Manager';
  panel.appendChild(title);

  const rows = layerManagerRows();
  if (rows.length === 0) {
    const empty = document.createElement('p');
    empty.className = 'group-desc';
    empty.textContent = 'No layers are currently active.';
    panel.appendChild(empty);
    return;
  }

  let draggedId = null;
  const list = document.createElement('div');
  list.className = 'wardrobe-layer-list';

  rows.forEach(layer => {
    const controls = ensureLayerControls(layer.id);
    const source = DOLL_CONFIG.layers.find(l => l.id === layer.id) || layer;
    const layerKind = layer.category === 'wardrobe'
      ? slotLabel(layer.subcategory)
      : `${layer.category || 'layer'} / ${layer.subcategory || 'base'}`;

    const row = document.createElement('div');
    row.className = `wardrobe-layer-row${layer.isActiveLayer ? '' : ' muted'}`;
    row.draggable = true;
    row.dataset.layerId = layer.id;
    row.title = `id: ${layer.id} · base z: ${baseComputedZ(layer)} · file: ${layer.file || 'none'}`;

    // drag handle
    const handle = document.createElement('span');
    handle.className = 'layer-drag-handle';
    handle.textContent = '⠿';
    row.appendChild(handle);

    // name + kind
    const metaCol = document.createElement('div');
    metaCol.className = 'wardrobe-layer-meta';
    const nameInput = document.createElement('input');
    nameInput.type = 'text';
    nameInput.className = 'wardrobe-layer-name-input';
    nameInput.value = displayLayerName(layer);
    nameInput.addEventListener('mousedown', e => e.stopPropagation());
    nameInput.addEventListener('change', () => {
      const next = nameInput.value.trim();
      if (!next) { nameInput.value = displayLayerName(layer); return; }
      pushHistory();
      source.name = next;
      controls.customName = next;
      renderWardrobeLayerStack(targetContainer);
      renderDoll(targetContainer);
    });
    const sub = document.createElement('span');
    sub.className = 'wardrobe-layer-sub';
    sub.textContent = `${layer.isActiveLayer ? 'active' : 'inactive'} · ${layerKind}`;
    metaCol.appendChild(nameInput);
    metaCol.appendChild(sub);
    row.appendChild(metaCol);

    // Z order: numeric input + back/front nudge buttons
    const orderWrap = document.createElement('div');
    orderWrap.className = 'wardrobe-layer-order';
    const zInput = document.createElement('input');
    zInput.type = 'number';
    zInput.className = 'layer-z-input';
    zInput.title = 'Z index';
    zInput.value = String(layer.computedZ);
    zInput.addEventListener('mousedown', e => e.stopPropagation());
    zInput.addEventListener('change', () => {
      const next = parseInt(zInput.value, 10);
      if (!Number.isFinite(next)) { zInput.value = String(layer.computedZ); return; }
      pushHistory();
      controls.zOffset = Math.max(-9999, Math.min(9999, next - baseComputedZ(layer)));
      renderWardrobeLayerStack(targetContainer);
      renderDoll(targetContainer);
    });
    const backBtn = document.createElement('button');
    backBtn.type = 'button';
    backBtn.className = 'layer-order-btn';
    backBtn.title = 'Move one step back (behind)';
    backBtn.textContent = '▼';
    backBtn.addEventListener('click', () => {
      const all = layerManagerRows();
      const idx = all.findIndex(r => r.id === layer.id);
      if (idx < all.length - 1) reorderWardrobeLayer(layer.id, all[idx + 1].id, targetContainer);
    });
    const frontBtn = document.createElement('button');
    frontBtn.type = 'button';
    frontBtn.className = 'layer-order-btn';
    frontBtn.title = 'Move one step front (in front)';
    frontBtn.textContent = '▲';
    frontBtn.addEventListener('click', () => {
      const all = layerManagerRows();
      const idx = all.findIndex(r => r.id === layer.id);
      if (idx > 0) reorderWardrobeLayer(layer.id, all[idx - 1].id, targetContainer);
    });
    orderWrap.appendChild(zInput);
    orderWrap.appendChild(backBtn);
    orderWrap.appendChild(frontBtn);
    row.appendChild(orderWrap);

    // opacity
    const opacityWrap = document.createElement('div');
    opacityWrap.className = 'wardrobe-opacity-control';
    const opacityLabel = document.createElement('span');
    opacityLabel.textContent = `${controls.opacity}%`;
    const opacitySlider = document.createElement('input');
    opacitySlider.type = 'range';
    opacitySlider.min = '0';
    opacitySlider.max = '100';
    opacitySlider.step = '5';
    opacitySlider.value = String(controls.opacity);
    opacitySlider.addEventListener('mousedown', e => e.stopPropagation());
    opacitySlider.addEventListener('input', () => {
      if (opacitySlider.dataset.dirty !== 'true') { pushHistory(); opacitySlider.dataset.dirty = 'true'; }
      controls.opacity = parseInt(opacitySlider.value, 10);
      opacityLabel.textContent = `${controls.opacity}%`;
      renderDoll(targetContainer);
    });
    opacitySlider.addEventListener('change', () => { opacitySlider.dataset.dirty = 'false'; });
    opacityWrap.appendChild(opacityLabel);
    opacityWrap.appendChild(opacitySlider);
    row.appendChild(opacityWrap);

    // duplicate + delete
    const actionsWrap = document.createElement('div');
    actionsWrap.className = 'wardrobe-layer-actions';
    const dupBtn = document.createElement('button');
    dupBtn.type = 'button';
    dupBtn.className = 'layer-icon-btn';
    dupBtn.title = 'Duplicate layer';
    dupBtn.textContent = '⧉';
    dupBtn.addEventListener('click', () => duplicateLayer(layer, targetContainer));
    const delBtn = document.createElement('button');
    delBtn.type = 'button';
    delBtn.className = 'layer-icon-btn layer-delete-btn';
    delBtn.title = 'Delete layer';
    delBtn.textContent = '✕';
    delBtn.addEventListener('click', () => deleteLayer(layer, targetContainer));
    actionsWrap.appendChild(dupBtn);
    actionsWrap.appendChild(delBtn);
    row.appendChild(actionsWrap);

    // visibility toggle
    const visBtn = document.createElement('button');
    visBtn.type = 'button';
    visBtn.className = 'layer-icon-btn';
    visBtn.title = controls.visible !== false ? 'Hide layer' : 'Show layer';
    visBtn.textContent = controls.visible !== false ? '●' : '○';
    visBtn.addEventListener('click', () => {
      pushHistory();
      controls.visible = controls.visible === false;
      renderWardrobeLayerStack(targetContainer);
      renderDoll(targetContainer);
    });
    row.appendChild(visBtn);

    // drag-and-drop reorder
    row.addEventListener('dragstart', e => {
      draggedId = layer.id;
      row.classList.add('dragging');
      e.dataTransfer.effectAllowed = 'move';
      e.dataTransfer.setData('text/plain', layer.id);
    });
    row.addEventListener('dragend', () => {
      draggedId = null;
      row.classList.remove('dragging');
      list.querySelectorAll('.drop-target').forEach(el => el.classList.remove('drop-target'));
    });
    row.addEventListener('dragover', e => {
      e.preventDefault();
      e.dataTransfer.dropEffect = 'move';
      if (row.dataset.layerId !== draggedId) {
        list.querySelectorAll('.drop-target').forEach(el => el.classList.remove('drop-target'));
        row.classList.add('drop-target');
      }
    });
    row.addEventListener('dragleave', () => row.classList.remove('drop-target'));
    row.addEventListener('drop', e => {
      e.preventDefault();
      row.classList.remove('drop-target');
      const fromId = e.dataTransfer.getData('text/plain') || draggedId;
      reorderWardrobeLayer(fromId, layer.id, targetContainer);
    });

    list.appendChild(row);
  });

  panel.appendChild(list);
}

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
