import { state, DOLL_CONFIG, TOGGLE_GROUPS, pushHistory } from './state.js';
import { renderDoll } from './render.js';

export function updateActiveOptionButton(slot, value) {
  const buttons = document.querySelectorAll(`[data-slot="${slot}"]`);
  buttons.forEach(btn => {
    btn.classList.toggle('active', btn.dataset.val === value);
  });
}

export function buildUI(targetContainer) {
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

      let previewClass = 'none-bg';
      let previewText = '';
      if (opt.value === 'skin_wear') {
        previewClass = 'skin-bg';
      } else if (opt.value === 'clothing') {
        if (slot === 'topwear') previewClass = 'cloth-top-bg';
        else if (slot === 'dress') previewClass = 'cloth-dress-bg';
        else if (slot === 'bottomwear') previewClass = 'cloth-bot-bg';
        else if (slot === 'legwear') previewClass = 'cloth-leg-bg';
        else if (slot === 'handwear') previewClass = 'cloth-hand-bg';
        else if (slot === 'outerwear') previewClass = 'cloth-outerwear-bg';
        else if (slot === 'skirt') previewClass = 'cloth-skirt-bg';
        else if (slot === 'pants') previewClass = 'cloth-pants-bg';
        else previewClass = 'cloth-generic-bg';
      } else if (opt.value === 'none') {
        previewText = '';
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
        pushHistory();
        gridDiv.querySelectorAll('.option-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        state.wardrobe[slot] = opt.value;

        // Dress clothing hides topwear and bottomwear
        if (slot === 'dress' && opt.value === 'clothing') {
          state.wardrobe.topwear = 'skin_wear';
          state.wardrobe.bottomwear = 'skin_wear';
          document.querySelectorAll('[data-slot="topwear"]').forEach(b =>
            b.classList.toggle('active', b.dataset.val === 'skin_wear')
          );
          document.querySelectorAll('[data-slot="bottomwear"]').forEach(b =>
            b.classList.toggle('active', b.dataset.val === 'skin_wear')
          );
        }

        renderDoll(targetContainer);
      });

      gridDiv.appendChild(btn);
    });

    groupDiv.appendChild(gridDiv);
    wardrobeContainer.appendChild(groupDiv);
  });

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
      if (o.value === 'front_body') optEl.selected = true;
      select.appendChild(optEl);
    });

    select.addEventListener('change', (e) => {
      pushHistory();
      state.wardrobeDepth['handwear'] = e.target.value;
      renderDoll(targetContainer);
    });
    state.wardrobeDepth['handwear'] = 'front_body';

    wrapper.appendChild(select);
    depthContainer.appendChild(wrapper);
  }

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
