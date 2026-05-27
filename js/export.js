import { DOLL_CONFIG, state, exportStateJSON, getBaseLayers } from './state.js';
import { localImageCache, localBlobCache, generateDynamicBodyReferenceCanvas } from './render.js';
import { downloadBlob, loadImage } from './utils.js';

const SILHOUETTE_EXCLUDED_CATEGORIES = new Set(['hair']);
const SILHOUETTE_FILL_RGB = [80, 80, 80];

// For ML conditioning (MediaPipe pose + ONNX depth), we want a body image
// with enough structure for the models to detect pose / estimate depth,
// without anatomical pixels. Composite: face / neck / ears (head shape),
// eye details (orientation cue for pose), and clothing layers (cover the
// body and provide structure). Hair is included for head/neck orientation.
const ML_BODY_EXCLUDED_CATEGORIES = new Set();

export async function generateBodySilhouetteCanvas() {
  const docW = DOLL_CONFIG.canvas.width;
  const docH = DOLL_CONFIG.canvas.height;
  const canvas = document.createElement('canvas');
  canvas.width = docW;
  canvas.height = docH;
  const ctx = canvas.getContext('2d');

  // Union the alphas of every layer that occupies body space. Hair expands
  // outside the body outline so it's excluded. Wardrobe layers stand in for
  // the body shape when no skin/body layer exists in the PSD.
  for (const layer of DOLL_CONFIG.layers) {
    if (SILHOUETTE_EXCLUDED_CATEGORIES.has(layer.category)) continue;
    const src = localImageCache[layer.file];
    if (!src) continue;
    try {
      const img = await loadImage(src);
      ctx.drawImage(img, 0, 0, docW, docH);
    } catch (err) {
      console.warn(`silhouette: could not load ${layer.file}:`, err);
    }
  }

  // Strip RGB content. Output is a binary alpha mask filled with a neutral
  // gray — no anatomical pixels remain.
  const data = ctx.getImageData(0, 0, docW, docH);
  const px = data.data;
  for (let i = 0; i < px.length; i += 4) {
    if (px[i + 3] > 10) {
      px[i]     = SILHOUETTE_FILL_RGB[0];
      px[i + 1] = SILHOUETTE_FILL_RGB[1];
      px[i + 2] = SILHOUETTE_FILL_RGB[2];
      px[i + 3] = 255;
    } else {
      px[i + 3] = 0;
    }
  }
  ctx.putImageData(data, 0, 0);
  return canvas;
}

export async function downloadBodySilhouette() {
  const canvas = await generateBodySilhouetteCanvas();
  const blob = await new Promise(res => canvas.toBlob(res, 'image/png'));
  downloadBlob(blob, 'body_silhouette.png');
}

export async function generateBodyCompositeCanvas() {
  const docW = DOLL_CONFIG.canvas.width;
  const docH = DOLL_CONFIG.canvas.height;

  // Preferred path: delegate to the canonical naked-body composer (render.js)
  // so the inpaint base is identical to what the active-view doll preview is
  // showing — same layer selection (getBaseLayers: non-wardrobe + skin_wear
  // options), same visibility toggles, same per-category/subcategory offsets.
  // Whenever there are base layers to render, trust this path; checking the
  // rendered canvas for "content" via pixel sampling is fragile (e.g. PNG
  // imports center the character on the canvas — top-left is always
  // transparent regardless of whether the body rendered correctly).
  if (getBaseLayers().length > 0) {
    return generateDynamicBodyReferenceCanvas();
  }

  // Fallback: no compositable body layers (e.g. user dropped a body_ref PNG
  // directly without a PSD layer set). Use the frozen reference if present.
  const canvas = document.createElement('canvas');
  canvas.width = docW;
  canvas.height = docH;
  const ctx = canvas.getContext('2d');
  ctx.fillStyle = '#ffffff';
  ctx.fillRect(0, 0, docW, docH);
  if (DOLL_CONFIG.body_ref) {
    try {
      const img = await loadImage(DOLL_CONFIG.body_ref);
      ctx.drawImage(img, 0, 0, docW, docH);
    } catch (err) {
      console.warn('body_ref load failed, returning white canvas:', err);
    }
  }
  return canvas;
}

export async function generateSkinCompositeCanvas() {
  const docW = DOLL_CONFIG.canvas.width;
  const docH = DOLL_CONFIG.canvas.height;
  const canvas = document.createElement('canvas');
  canvas.width = docW;
  canvas.height = docH;
  const ctx = canvas.getContext('2d');

  // Composite only skin_wear layers (the naked skeleton) — the ground truth
  // for cel-shading reference. These are wardrobe layers with skin_wear option.
  for (const layer of DOLL_CONFIG.layers) {
    if (layer.optionValue !== 'skin_wear') continue;
    const src = localImageCache[layer.file];
    if (!src) continue;
    try {
      const img = await loadImage(src);
      ctx.drawImage(img, 0, 0, docW, docH);
    } catch (err) {
      console.warn(`skin composite: could not load ${layer.file}:`, err);
    }
  }
  return canvas;
}

export async function downloadReferencePack() {
  const silCanvas = await generateBodySilhouetteCanvas();
  const bodyCanvas = await generateBodyCompositeCanvas();
  const silBlob = await new Promise(res => silCanvas.toBlob(res, 'image/png'));
  const bodyBlob = await new Promise(res => bodyCanvas.toBlob(res, 'image/png'));

  const fd = new FormData();
  fd.append('image', silBlob, 'body_silhouette.png');
  fd.append('body', bodyBlob, 'body_composite.png');

  const res = await fetch('/api/reference-pack', { method: 'POST', body: fd });
  if (!res.ok) {
    let detail = res.statusText;
    try { const j = await res.json(); detail = j.detail || detail; } catch {}
    throw new Error(`HTTP ${res.status}: ${detail}`);
  }
  const zipBlob = await res.blob();
  downloadBlob(zipBlob, 'reference_pack.zip');
}

export function generateConfigJSString() {
  if (!DOLL_CONFIG.defaults) DOLL_CONFIG.defaults = {};
  DOLL_CONFIG.defaults.offsets = state.offsets;

  return `// Dynamic Paper Doll Studio Configuration
// Automatically generated by Paper Doll Studio Client

window.DOLL_CONFIG = ${JSON.stringify(DOLL_CONFIG, null, 2)};
`;
}

export function downloadConfig() {
  const configStr = generateConfigJSString();
  const blob = new Blob([configStr], { type: 'application/javascript;charset=utf-8' });
  downloadBlob(blob, 'doll_config.js');
}

export function downloadStateJSON() {
  const jsonStr = exportStateJSON();
  const blob = new Blob([jsonStr], { type: 'application/json;charset=utf-8' });
  const timestamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
  downloadBlob(blob, `paperdoll-state-${timestamp}.json`);
}

export async function exportZIP(onProgress) {
  const JSZip = window.JSZip;
  if (!JSZip) throw new Error('JSZip library not loaded');

  const zip = new JSZip();

  // Config
  zip.file('doll_config.js', generateConfigJSString());
  zip.file('project.json', JSON.stringify({
    version: 1,
    canvas: DOLL_CONFIG.canvas,
    layers: DOLL_CONFIG.layers,
    wardrobe: DOLL_CONFIG.wardrobe,
    defaults: DOLL_CONFIG.defaults,
    meta: { ...(DOLL_CONFIG.meta || {}), updatedAt: new Date().toISOString() }
  }, null, 2));

  // Assets
  const assetsFolder = zip.folder('public/assets');
  let processed = 0;
  const total = DOLL_CONFIG.layers.length;

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
    processed++;
    if (onProgress) onProgress(processed, total);
  }

  // Include core app files
  // Note: project.json is NOT fetched from the server here because it is
  // dynamically generated above with the current DOLL_CONFIG (which includes
  // any compiled-asset wardrobe entries).  Fetching the static server copy
  // would overwrite those dynamic changes.
  try {
    const files = ['index.html', 'style.css'];
    for (const f of files) {
      const res = await fetch(f);
      if (res.ok) zip.file(f, await res.blob());
    }
    // Add wardrobe manifest and every compiled asset folder it references
    let manifest = [];
    try {
      const manifestRes = await fetch('public/assets/wardrobe_manifest.json');
      if (manifestRes.ok) {
        const manifestBlob = await manifestRes.blob();
        assetsFolder.file('wardrobe_manifest.json', manifestBlob);
        manifest = JSON.parse(await manifestBlob.text());
      }
    } catch (err) {
      console.warn('Could not include wardrobe_manifest.json:', err);
    }
    for (const entry of manifest) {
      const cat = entry.category;
      const aid = entry.asset_id;
      if (!cat || !aid) continue;
      const base = `compiled/${cat}/${aid}`;
      // metadata.json (drives per-layer list below)
      let metadata = null;
      try {
        const mRes = await fetch(`public/assets/${base}/metadata.json`);
        if (mRes.ok) {
          const mBlob = await mRes.blob();
          assetsFolder.file(`${base}/metadata.json`, mBlob);
          metadata = JSON.parse(await mBlob.text());
        }
      } catch (err) {
        console.warn(`Could not include ${base}/metadata.json:`, err);
      }
      // preview.png
      try {
        const pRes = await fetch(`public/assets/${base}/preview.png`);
        if (pRes.ok) assetsFolder.file(`${base}/preview.png`, await pRes.blob());
      } catch (err) {
        console.warn(`Could not include ${base}/preview.png:`, err);
      }
      // per-layer PNGs from metadata.layers[].file
      if (metadata && Array.isArray(metadata.layers)) {
        for (const layer of metadata.layers) {
          if (!layer.file) continue;
          try {
            const lRes = await fetch(`public/assets/${base}/${layer.file}`);
            if (lRes.ok) assetsFolder.file(`${base}/${layer.file}`, await lRes.blob());
          } catch (err) {
            console.warn(`Could not include ${base}/${layer.file}:`, err);
          }
        }
      }
      // fit_debug/anchors.json (best effort; non-fitted categories won't have it)
      try {
        const aRes = await fetch(`public/assets/${base}/fit_debug/anchors.json`);
        if (aRes.ok) assetsFolder.file(`${base}/fit_debug/anchors.json`, await aRes.blob());
      } catch (err) {
        /* expected for non-fitted categories */
      }
    }
    // Add JS modules
    const moduleFiles = ['js/utils.js', 'js/state.js', 'js/render.js', 'js/wardrobe.js', 'js/calibration.js', 'js/import.js', 'js/export.js', 'js/cleanup.js', 'app.js'];
    for (const f of moduleFiles) {
      const res = await fetch(f);
      if (res.ok) zip.file(f, await res.blob());
    }
  } catch (err) {
    console.warn('Could not include core app files in ZIP:', err);
  }

  const zipContent = await zip.generateAsync({ type: 'blob' });
  downloadBlob(zipContent, 'paperdoll_project.zip');
  return zipContent;
}
