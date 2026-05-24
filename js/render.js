import { state, DOLL_CONFIG, getActiveLayers, getBaseLayers, TOGGLE_GROUPS } from './state.js';
import { loadImage, applyBakeTransform } from './utils.js';

export let localImageCache = {};
export let localBlobCache = {};

export let pendingAssetImage = null;
export let pendingAssetFile = null;
export const alignSettings = {
  x: 0,
  y: 0,
  scaleX: 1.0,
  scaleY: 1.0,
  opacity: 50
};

// Optional override: when set, renderDoll's pending overlay draws THIS image
// instead of pendingAssetImage. Used by the importer's live preview to show
// the chroma-keyed / body-subtracted / AI-cleaned result without fighting
// renderDoll's normal rendering path.
export let pendingPreviewImage = null;
export let pendingPreviewIsBaked = false;

export function setPendingAsset(file, image) {
  pendingAssetFile = file;
  pendingAssetImage = image;
}

export function setPendingPreviewImage(image, options = {}) {
  pendingPreviewImage = image;
  pendingPreviewIsBaked = !!options.baked;
}

export function clearPendingAsset() {
  pendingAssetFile = null;
  pendingAssetImage = null;
  pendingPreviewImage = null;
  pendingPreviewIsBaked = false;
}

export function clearImageCache() {
  Object.values(localImageCache).forEach(url => URL.revokeObjectURL(url));
  localImageCache = {};
  localBlobCache = {};
}

export function cacheImage(filename, objectUrl, blob) {
  localImageCache[filename] = objectUrl;
  if (blob) localBlobCache[filename] = blob;
}

export function renderDoll(targetContainer) {
  targetContainer.innerHTML = '';
  const activeLayers = getActiveLayers();

  activeLayers.forEach(layer => {
    const img = document.createElement('img');
    img.src = localImageCache[layer.file] || `public/assets/${layer.file}`;
    img.alt = layer.id;
    img.className = 'doll-layer-img';
    img.style.zIndex = layer.computedZ;
    img.style.opacity = (layer.opacity ?? 100) / 100;

    let x = 0;
    let y = 0;

    if (state.offsets.rig_offset) {
      x += state.offsets.rig_offset.x;
      y += state.offsets.rig_offset.y;
    }

    if (layer.file.startsWith('clothing_')) {
      x += state.offsets.clothed_assets.x;
      y += state.offsets.clothed_assets.y;
    }

    if (layer.category && state.offsets[layer.category]) {
      x += state.offsets[layer.category].x;
      y += state.offsets[layer.category].y;
    }

    if (layer.subcategory && state.offsets[layer.subcategory] && layer.subcategory !== layer.category) {
      x += state.offsets[layer.subcategory].x;
      y += state.offsets[layer.subcategory].y;
    }

    let filters = '';
    if (layer.dyeable) {
      if (layer.category === 'hair') {
        filters = `hue-rotate(${state.dyes.hair.hue}deg) saturate(${state.dyes.hair.sat}%) brightness(${state.dyes.hair.light}%)`;
      } else if (layer.subcategory === 'irides') {
        filters = `hue-rotate(${state.dyes.eyes.hue}deg) saturate(130%)`;
      }
    }

    img.style.transform = `translate(${x}px, ${y}px)`;
    if (filters) img.style.filter = filters;

    targetContainer.appendChild(img);
  });

  if (pendingAssetImage && alignSettings.opacity > 0) {
    const docW = DOLL_CONFIG.canvas?.width || 768;
    const docH = DOLL_CONFIG.canvas?.height || 768;
    const overlay = document.createElement('canvas');
    overlay.width = docW;
    overlay.height = docH;
    overlay.className = 'doll-layer-img pending-alignment-overlay';
    overlay.style.zIndex = 300;
    overlay.style.opacity = alignSettings.opacity / 100;
    overlay.style.pointerEvents = 'none';
    const source = pendingPreviewImage || pendingAssetImage;
    const ctx = overlay.getContext('2d');
    if (pendingPreviewImage && pendingPreviewIsBaked) {
      ctx.drawImage(source, 0, 0, docW, docH);
    } else {
      applyBakeTransform(ctx, source, docW, docH, alignSettings);
    }
    targetContainer.appendChild(overlay);
  }
}

export function updateViewportTransform(dollContainer) {
  dollContainer.style.transform = `scale(${state.zoom})`;
}

export async function generateDynamicBodyReferenceCanvas() {
  const canvas = document.createElement('canvas');
  canvas.width = DOLL_CONFIG.canvas.width;
  canvas.height = DOLL_CONFIG.canvas.height;
  const ctx = canvas.getContext('2d');

  const baseLayers = getBaseLayers();

  for (const layer of baseLayers) {
    let isVisible = true;
    if (layer.category !== 'wardrobe') {
      const toggleGroupId = Object.keys(TOGGLE_GROUPS).find(groupId =>
        TOGGLE_GROUPS[groupId].subcats.includes(layer.subcategory)
      );
      if (toggleGroupId !== undefined) {
        isVisible = state.toggles[toggleGroupId] !== false;
      }
    }
    if (!isVisible) continue;

    const imgSource = localImageCache[layer.file] || `public/assets/${layer.file}`;
    try {
      const img = await loadImage(imgSource);

      let x = 0, y = 0;
      if (state.offsets.rig_offset) {
        x += state.offsets.rig_offset.x;
        y += state.offsets.rig_offset.y;
      }
      if (layer.category && state.offsets[layer.category]) {
        x += state.offsets[layer.category].x;
        y += state.offsets[layer.category].y;
      }
      if (layer.subcategory && state.offsets[layer.subcategory] && layer.subcategory !== layer.category) {
        x += state.offsets[layer.subcategory].x;
        y += state.offsets[layer.subcategory].y;
      }

      ctx.drawImage(img, x, y, DOLL_CONFIG.canvas.width, DOLL_CONFIG.canvas.height);
    } catch (e) {
      console.warn(`Could not draw base layer ${layer.file} for reference body:`, e);
    }
  }

  return canvas;
}

export function updateDollCursor(dollContainer) {
  if (pendingAssetImage && alignSettings.opacity > 0) {
    dollContainer.style.cursor = 'move';
  } else {
    dollContainer.style.cursor = 'default';
  }
}
