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

  // Depth overrides (handwear only for now)
  const depthContainer = document.getElementById('depth-controls-container');
  depthContainer.innerHTML = '';
  if (DOLL_CONFIG.wardrobe.handwear) {
    const wrapper = document.createElement('div');
    wrapper.className = 'select-wrapper';
    wrapper.style.cssText = 'margin-top: 0.8rem';

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
      if (o.value === (state.wardrobeDepth['handwear'] || 'front_body')) optEl.selected = true;
      select.appendChild(optEl);
    });

    select.addEventListener('change', (e) => {
      pushHistory();
      state.wardrobeDepth['handwear'] = e.target.value;
      renderWardrobeLayerStack(targetContainer);
      renderDoll(targetContainer);
    });
    if (!state.wardrobeDepth['handwear']) state.wardrobeDepth['handwear'] = 'front_body';

    wrapper.appendChild(select);
    depthContainer.appendChild(wrapper);
  }

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

function reorderWardrobeLayer(draggedId, targetId, targetContainer) {
  if (!draggedId || !targetId || draggedId === targetId) return;
  const rows = activeWardrobeLayersForStack();
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
    controls.zOffset = Math.max(-200, Math.min(200, zSlots[idx] - baseComputedZ(layer)));
  });
  renderWardrobeLayerStack(targetContainer);
  renderDoll(targetContainer);
}

function activeWardrobeLayersForStack() {
  const activeIds = new Set(getActiveLayers().filter(l => l.category === 'wardrobe').map(l => l.id));
  const hiddenActive = DOLL_CONFIG.layers.filter(layer => {
    if (layer.category !== 'wardrobe') return false;
    if (state.layerControls[layer.id]?.visible !== false) return false;
    const slotConfig = DOLL_CONFIG.wardrobe[layer.subcategory];
    const selected = slotConfig?.options.find(o => o.value === state.wardrobe[layer.subcategory]);
    return selected?.layers.includes(layer.id);
  });
  const visibleActive = getActiveLayers().filter(l => l.category === 'wardrobe');
  hiddenActive.forEach(layer => {
    if (!activeIds.has(layer.id)) {
      visibleActive.push({
        ...layer,
        name: state.layerControls[layer.id]?.customName || layer.name,
        computedZ: layer.z + (state.layerControls[layer.id]?.zOffset || 0),
        opacity: state.layerControls[layer.id]?.opacity ?? 100,
      });
    }
  });
  return visibleActive.sort((a, b) => b.computedZ - a.computedZ);
}

function renderWardrobeLayerStack(targetContainer) {
  const depthContainer = document.getElementById('depth-controls-container');
  if (!depthContainer) return;

  let panel = document.getElementById('wardrobe-layer-stack-panel');
  if (!panel) {
    panel = document.createElement('div');
    panel.id = 'wardrobe-layer-stack-panel';
    panel.className = 'control-group wardrobe-layer-stack';
    depthContainer.appendChild(panel);
  }

  panel.textContent = '';
  const title = document.createElement('h3');
  title.textContent = 'Wardrobe Layer Stack';
  panel.appendChild(title);

  const rows = activeWardrobeLayersForStack();
  if (rows.length === 0) {
    const empty = document.createElement('p');
    empty.className = 'group-desc';
    empty.textContent = 'No wardrobe layers are currently active.';
    panel.appendChild(empty);
    return;
  }

  const list = document.createElement('div');
  list.className = 'wardrobe-layer-list';

  rows.forEach(layer => {
    const controls = ensureLayerControls(layer.id);
    const row = document.createElement('div');
    row.className = `wardrobe-layer-row${controls.visible === false ? ' muted' : ''}`;
    row.draggable = true;
    row.dataset.layerId = layer.id;
    row.addEventListener('dragstart', (e) => {
      e.dataTransfer.effectAllowed = 'move';
      e.dataTransfer.setData('text/plain', layer.id);
      row.classList.add('dragging');
    });
    row.addEventListener('dragend', () => {
      row.classList.remove('dragging');
      document.querySelectorAll('.wardrobe-layer-row.drop-target').forEach(el => el.classList.remove('drop-target'));
    });
    row.addEventListener('dragover', (e) => {
      e.preventDefault();
      row.classList.add('drop-target');
    });
    row.addEventListener('dragleave', () => row.classList.remove('drop-target'));
    row.addEventListener('drop', (e) => {
      e.preventDefault();
      row.classList.remove('drop-target');
      reorderWardrobeLayer(e.dataTransfer.getData('text/plain'), layer.id, targetContainer);
    });

    const visibility = document.createElement('button');
    visibility.type = 'button';
    visibility.className = 'layer-icon-btn';
    visibility.title = controls.visible === false ? 'Show layer' : 'Hide layer';
    visibility.textContent = controls.visible === false ? 'Show' : 'Hide';
    visibility.addEventListener('click', () => {
      pushHistory();
      controls.visible = controls.visible === false;
      renderWardrobeLayerStack(targetContainer);
      renderDoll(targetContainer);
    });
    row.appendChild(visibility);

    const meta = document.createElement('div');
    meta.className = 'wardrobe-layer-meta';
    const name = document.createElement('input');
    name.className = 'wardrobe-layer-name-input';
    name.value = displayLayerName(layer);
    name.title = 'Layer display name';
    name.addEventListener('dragstart', e => e.preventDefault());
    name.addEventListener('keydown', e => {
      if (e.key === 'Enter') name.blur();
    });
    name.addEventListener('focus', () => {
      name.dataset.originalValue = displayLayerName(layer);
    });
    name.addEventListener('change', () => {
      const nextName = name.value.trim();
      const prevName = name.dataset.originalValue || displayLayerName(layer);
      if (!nextName) {
        name.value = prevName;
        return;
      }
      if (nextName === prevName) return;
      pushHistory();
      controls.customName = nextName;
      renderWardrobeLayerStack(targetContainer);
      renderDoll(targetContainer);
    });
    const sub = document.createElement('span');
    sub.className = 'wardrobe-layer-sub';
    sub.textContent = `${slotLabel(layer.subcategory)} · z ${layer.computedZ}`;
    meta.appendChild(name);
    meta.appendChild(sub);
    row.appendChild(meta);

    const order = document.createElement('div');
    order.className = 'wardrobe-layer-order';
    [
      { label: 'Back', delta: -5 },
      { label: 'Front', delta: 5 },
    ].forEach(({ label, delta }) => {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'layer-order-btn';
      btn.textContent = label;
      btn.addEventListener('click', () => {
        pushHistory();
        controls.zOffset = Math.max(-80, Math.min(80, (controls.zOffset || 0) + delta));
        renderWardrobeLayerStack(targetContainer);
        renderDoll(targetContainer);
      });
      order.appendChild(btn);
    });
    row.appendChild(order);

    const opacityWrap = document.createElement('label');
    opacityWrap.className = 'wardrobe-opacity-control';
    const opacityText = document.createElement('span');
    opacityText.textContent = `${controls.opacity}%`;
    const opacity = document.createElement('input');
    opacity.type = 'range';
    opacity.min = '0';
    opacity.max = '100';
    opacity.step = '5';
    opacity.value = String(controls.opacity);
    opacity.addEventListener('input', (e) => {
      if (opacity.dataset.dirty !== 'true') {
        pushHistory();
        opacity.dataset.dirty = 'true';
      }
      controls.opacity = parseInt(e.target.value, 10);
      opacityText.textContent = `${controls.opacity}%`;
      renderDoll(targetContainer);
    });
    opacity.addEventListener('change', () => {
      opacity.dataset.dirty = 'false';
      renderWardrobeLayerStack(targetContainer);
      renderDoll(targetContainer);
    });
    opacityWrap.appendChild(opacityText);
    opacityWrap.appendChild(opacity);
    row.appendChild(opacityWrap);

    const reset = document.createElement('button');
    reset.type = 'button';
    reset.className = 'layer-reset-btn';
    reset.textContent = 'Reset';
    reset.addEventListener('click', () => {
      pushHistory();
      state.layerControls[layer.id] = { visible: true, opacity: 100, zOffset: 0 };
      renderWardrobeLayerStack(targetContainer);
      renderDoll(targetContainer);
    });
    row.appendChild(reset);

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
