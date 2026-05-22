import { DOLL_CONFIG, state } from './state.js';
import { renderDoll, localImageCache, pendingAssetImage, pendingAssetFile, alignSettings, setPendingAsset } from './render.js';
import { loadImage, getBoundingBox, canvasToBlob } from './utils.js';

let anchorsEnabled = false;

const MANUAL_PLACE_ANCHORS = {
  dress: ['strap_left', 'strap_right', 'bust_left', 'bust_right'],
};

let pendingPlacementQueue = [];

export function isAnchorInteractionEnabled() {
  return anchorsEnabled;
}

function hasPendingPlacements() {
  return pendingPlacementQueue.length > 0;
}

function updatePlacementStatus() {
  const fitStatus = document.getElementById('fit-status');
  const confirmBtn = document.getElementById('btn-confirm-anchors');
  if (hasPendingPlacements()) {
    if (fitStatus) {
      fitStatus.style.display = 'block';
      fitStatus.innerHTML = `Click on the garment to place: <strong>${pendingPlacementQueue[0]}</strong> (${pendingPlacementQueue.length} remaining)`;
    }
    if (confirmBtn) confirmBtn.disabled = true;
  } else {
    if (fitStatus) {
      fitStatus.style.display = 'block';
      fitStatus.innerHTML = `All required anchors placed. Drag to refine, then click Confirm. <button class="btn btn-sm" onclick="document.getElementById('fit-status').style.display='none'">Dismiss</button>`;
    }
    if (confirmBtn) confirmBtn.disabled = false;
  }
  const overlay = document.getElementById('anchor-overlay-canvas');
  if (overlay) {
    overlay.style.pointerEvents = (anchorsEnabled || hasPendingPlacements()) ? 'auto' : 'none';
  }
}

export function initFitPreview(targetContainer) {
  wireSmartFit(targetContainer);
  wireAnchorToggle();
  wireConfirmAnchors();
}

function wireAnchorToggle() {
  const btn = document.getElementById('btn-toggle-anchor-edit');
  if (!btn) return;
  btn.addEventListener('click', () => {
    anchorsEnabled = !anchorsEnabled;
    btn.textContent = anchorsEnabled ? '🔒 Anchor Edit: ON' : '🔓 Anchor Edit: OFF';
    const canvas = document.getElementById('anchor-overlay-canvas');
    if (canvas) {
      canvas.style.pointerEvents = (anchorsEnabled || hasPendingPlacements()) ? 'auto' : 'none';
      canvas.style.cursor = anchorsEnabled ? 'default' : 'default';
    }
  });
}

function wireConfirmAnchors() {
  const btn = document.getElementById('btn-confirm-anchors');
  if (!btn) return;
  btn.addEventListener('click', () => {
    if (!anchorDragAnchors || Object.keys(anchorDragAnchors).length === 0) {
      alert('No anchors to confirm. Run Smart Fit first.');
      return;
    }
    confirmedAnchors = {};
    for (const [name, pos] of Object.entries(anchorDragAnchors)) {
      confirmedAnchors[name] = [Math.round(pos[0]), Math.round(pos[1])];
    }
    btn.textContent = '✓ Anchors Confirmed';
    btn.style.borderColor = '#4caf50';
    btn.style.color = '#4caf50';
    btn.disabled = true;
    const submitBtn = document.getElementById('btn-ingest-submit');
    if (submitBtn) submitBtn.disabled = false;
    reapplyFit();
  });
}

let fittedCanvas = null;
let inferredAnchors = {};
let confirmedAnchors = null;

export function getConfirmedAnchors() {
  return confirmedAnchors;
}

function wireSmartFit(targetContainer) {
  const btnSmartFit = document.getElementById('btn-smart-fit');
  const btnToggleFit = document.getElementById('btn-toggle-fit-preview');
  const anchorOverlay = document.getElementById('anchor-overlay-canvas');

  if (btnSmartFit) {
    btnSmartFit.addEventListener('click', async () => {
      if (!pendingAssetImage) {
        alert('Please select or drop an image asset first.');
        return;
      }
      clearFitPreview();
      await runSmartFit(targetContainer);
    });
  }

  if (btnToggleFit) {
    btnToggleFit.addEventListener('click', () => {
      toggleFitPreview(targetContainer);
    });
  }
}

function computeWidthProfile(ctx, w, h) {
  const imageData = ctx.getImageData(0, 0, w, h);
  const data = imageData.data;
  const leftEdges = [];
  const rightEdges = [];
  const widths = [];

  for (let y = 0; y < h; y++) {
    let left = null;
    let right = null;
    for (let x = 0; x < w; x++) {
      const idx = (y * w + x) * 4 + 3;
      if (data[idx] > 10) {
        if (left === null) left = x;
        right = x;
      }
    }
    leftEdges.push(left);
    rightEdges.push(right);
    widths.push(left !== null ? right - left : 0);
  }
  return { leftEdges, rightEdges, widths };
}

function inferGarmentAnchorsJS(canvas) {
  const ctx = canvas.getContext('2d');
  const w = canvas.width;
  const h = canvas.height;
  const { leftEdges, rightEdges, widths } = computeWidthProfile(ctx, w, h);

  let topY = null;
  let bottomY = null;
  for (let y = 0; y < h; y++) {
    if (widths[y] > 0) { topY = y; break; }
  }
  for (let y = h - 1; y >= 0; y--) {
    if (widths[y] > 0) { bottomY = y; break; }
  }

  if (topY === null || bottomY === null) return {};

  const garmentHeight = bottomY - topY;
  const anchors = {};

  function edgeXAt(y) {
    return { left: leftEdges[y], right: rightEdges[y] };
  }

  function centerXAt(y) {
    const e = edgeXAt(y);
    if (e.left === null) return null;
    return (e.left + e.right) / 2;
  }

  const neckY = topY + Math.max(Math.floor(garmentHeight * 0.03), 2);
  const cx = centerXAt(neckY);
  if (cx !== null) {
    anchors.neck = [cx, neckY];
  }

  const neckRegionEnd = topY + Math.max(Math.floor(garmentHeight * 0.08), 5);
  const shouldersRegionEnd = topY + Math.floor(garmentHeight * 0.40);
  let bestShoulderY = null;
  let bestShoulderWidth = 0;
  for (let y = neckRegionEnd; y < Math.min(shouldersRegionEnd, h); y++) {
    if (widths[y] > bestShoulderWidth) {
      bestShoulderWidth = widths[y];
      bestShoulderY = y;
    }
  }
  if (bestShoulderY !== null) {
    const e = edgeXAt(bestShoulderY);
    if (e.left !== null) {
      anchors.left_shoulder = [e.left, bestShoulderY];
      anchors.right_shoulder = [e.right, bestShoulderY];
    }
  }

  const waistStart = topY + Math.floor(garmentHeight * 0.30);
  const waistEnd = topY + Math.floor(garmentHeight * 0.60);
  let bestWaistY = null;
  let bestWaistWidth = Infinity;
  for (let y = waistStart; y < Math.min(waistEnd, h); y++) {
    if (widths[y] > 10 && widths[y] < bestWaistWidth) {
      bestWaistWidth = widths[y];
      bestWaistY = y;
    }
  }
  if (bestWaistY !== null) {
    const e = edgeXAt(bestWaistY);
    if (e.left !== null) {
      anchors.waist_left = [e.left, bestWaistY];
      anchors.waist_right = [e.right, bestWaistY];
    }
  }

  const hipStart = anchors.waist_left ? anchors.waist_left[1] + 1 : topY + Math.floor(garmentHeight * 0.40);
  const hipEnd = topY + Math.floor(garmentHeight * 0.75);
  let bestHipY = null;
  let bestHipWidth = 0;
  for (let y = hipStart; y < Math.min(hipEnd, h); y++) {
    if (widths[y] > 10 && widths[y] > bestHipWidth) {
      bestHipWidth = widths[y];
      bestHipY = y;
    }
  }
  if (bestHipY !== null) {
    const e = edgeXAt(bestHipY);
    if (e.left !== null) {
      anchors.hip_left = [e.left, bestHipY];
      anchors.hip_right = [e.right, bestHipY];
    }
  }

  let hemY = bottomY;
  const hemStart = topY + Math.floor(garmentHeight * 0.70);
  for (let y = hemStart; y <= bottomY; y++) {
    if (widths[y] > 5) hemY = y;
  }
  const hemE = edgeXAt(hemY);
  if (hemE.left !== null) {
    anchors.hem_left = [hemE.left, hemY];
    anchors.hem_right = [hemE.right, hemY];
  }

  return anchors;
}

const STABLE_RIG_ANCHORS = {
  dress: {
    neck: [384, 180],
    strap_left: [345, 210], strap_right: [423, 210],
    bust_left: [320, 310], bust_right: [448, 310],
    waist_left: [318, 420], waist_right: [446, 420],
    hip_left: [300, 440], hip_right: [468, 440],
    hem_left: [280, 620], hem_right: [488, 620],
  },
  topwear: {
    neck: [384, 180],
    left_shoulder: [304, 250], right_shoulder: [472, 250],
    waist_left: [318, 420], waist_right: [446, 420],
  },
  top: {
    neck: [384, 180],
    left_shoulder: [304, 250], right_shoulder: [472, 250],
    waist_left: [318, 420], waist_right: [446, 420],
  },
  skirt: {
    waist_left: [318, 420], waist_right: [446, 420],
    hip_left: [300, 440], hip_right: [468, 440],
    hem_left: [280, 620], hem_right: [488, 620],
  },
  pants: {
    waist_left: [318, 420], waist_right: [446, 420],
    hip_left: [300, 440], hip_right: [468, 440],
    knee_left: [296, 540], knee_right: [472, 540],
  },
  legwear: {
    waist_left: [318, 420], waist_right: [446, 420],
    hip_left: [300, 440], hip_right: [468, 440],
    knee_left: [296, 540], knee_right: [472, 540],
  },
  outerwear: {
    neck: [384, 180],
    left_shoulder: [304, 250], right_shoulder: [472, 250],
    waist_left: [318, 420], waist_right: [446, 420],
    hip_left: [300, 440], hip_right: [468, 440],
    hem_left: [280, 620], hem_right: [488, 620],
  },
};

function getRigAnchorsForCategory(category) {
  const cat = (category || 'topwear').toLowerCase();
  return STABLE_RIG_ANCHORS[cat] || STABLE_RIG_ANCHORS.dress;
}

function isPiecewiseCategory(category) {
  const cat = (category || '').toLowerCase();
  return cat === 'dress' || cat === 'outerwear';
}

function getUpperAnchorCandidates() {
  return ['neck', 'strap_left', 'strap_right',
          'bust_left', 'bust_right',
          'left_shoulder', 'right_shoulder',
          'waist_left', 'waist_right'];
}

function getLowerAnchorCandidates() {
  return ['waist_left', 'waist_right',
          'hip_left', 'hip_right',
          'hem_left', 'hem_right',
          'knee_left', 'knee_right',
          'ankle_left', 'ankle_right'];
}

function getSingleAnchorsForCategory(category) {
  const cat = (category || '').toLowerCase();
  const anchors = {
    dress:      ['neck', 'strap_left', 'strap_right', 'bust_left', 'bust_right',
                 'waist_left', 'waist_right', 'hip_left', 'hip_right',
                 'hem_left', 'hem_right'],
    topwear:    ['neck', 'left_shoulder', 'right_shoulder',
                 'waist_left', 'waist_right'],
    top:        ['neck', 'left_shoulder', 'right_shoulder',
                 'waist_left', 'waist_right'],
    skirt:      ['waist_left', 'waist_right', 'hip_left', 'hip_right',
                 'hem_left', 'hem_right'],
    pants:      ['waist_left', 'waist_right', 'hip_left', 'hip_right',
                 'knee_left', 'knee_right'],
    legwear:    ['waist_left', 'waist_right', 'hip_left', 'hip_right',
                 'knee_left', 'knee_right'],
    outerwear:  ['neck', 'left_shoulder', 'right_shoulder',
                 'waist_left', 'waist_right', 'hip_left', 'hip_right',
                 'hem_left', 'hem_right'],
  };
  return anchors[cat] || anchors.topwear;
}

function computeSplitY(rigAnchors) {
  for (const name of ['waist_left', 'waist_right', 'hip_left']) {
    if (rigAnchors[name]) return rigAnchors[name][1];
  }
  return null;
}

function computeFitParams(inferredAnchors, category, rigAnchors) {
  if (isPiecewiseCategory(category)) {
    const upperCandidates = getUpperAnchorCandidates();
    const lowerCandidates = getLowerAnchorCandidates();
    const upperSrc = [], upperDst = [];
    const lowerSrc = [], lowerDst = [];
    for (const name of upperCandidates) {
      if (inferredAnchors[name] && rigAnchors[name]) {
        upperSrc.push(inferredAnchors[name]);
        upperDst.push(rigAnchors[name]);
      }
    }
    for (const name of lowerCandidates) {
      if (inferredAnchors[name] && rigAnchors[name]) {
        lowerSrc.push(inferredAnchors[name]);
        lowerDst.push(rigAnchors[name]);
      }
    }
    const splitY = computeSplitY(rigAnchors);
    const upperParams = upperSrc.length >= 3 ? computeAffineForward(upperSrc, upperDst) : null;
    const lowerParams = lowerSrc.length >= 3 ? computeAffineForward(lowerSrc, lowerDst) : null;
    return { upperParams, lowerParams, splitY, upperSrc, lowerSrc };
  }
  const anchorNames = getSingleAnchorsForCategory(category);
  const srcPts = [], dstPts = [];
  for (const name of anchorNames) {
    if (inferredAnchors[name] && rigAnchors[name]) {
      srcPts.push(inferredAnchors[name]);
      dstPts.push(rigAnchors[name]);
    }
  }
  const params = srcPts.length >= 3 ? computeAffineForward(srcPts, dstPts) : null;
  return { upperParams: params, lowerParams: null, splitY: null, upperSrc: srcPts, lowerSrc: [] };
}

function applyPiecewiseBlend(docWidth, docHeight, srcCanvas, params, blendRadius) {
  if (blendRadius === undefined) blendRadius = 20;
  const { upperParams, lowerParams, splitY } = params;

  const resultCanvas = document.createElement('canvas');
  resultCanvas.width = docWidth;
  resultCanvas.height = docHeight;
  const resultCtx = resultCanvas.getContext('2d');

  if (!lowerParams || splitY === null) {
    if (upperParams) {
      const [a, b, c, d, e, f] = upperParams;
      resultCtx.setTransform(a, b, c, d, e, f);
      resultCtx.drawImage(srcCanvas, 0, 0);
    }
    return resultCanvas;
  }

  const upperCanvas = document.createElement('canvas');
  upperCanvas.width = docWidth;
  upperCanvas.height = docHeight;
  const upperCtx = upperCanvas.getContext('2d');
  const [ua, ub, uc, ud, ue, uf] = upperParams;
  upperCtx.setTransform(ua, ub, uc, ud, ue, uf);
  upperCtx.drawImage(srcCanvas, 0, 0);

  const lowerCanvas = document.createElement('canvas');
  lowerCanvas.width = docWidth;
  lowerCanvas.height = docHeight;
  const lowerCtx = lowerCanvas.getContext('2d');
  const [la, lb, lc, ld, le, lf] = lowerParams;
  lowerCtx.setTransform(la, lb, lc, ld, le, lf);
  lowerCtx.drawImage(srcCanvas, 0, 0);

  const blendStart = Math.max(0, splitY - blendRadius);
  const blendEnd = Math.min(docHeight, splitY + blendRadius);

  const maskCanvas = document.createElement('canvas');
  maskCanvas.width = docWidth;
  maskCanvas.height = docHeight;
  const maskCtx = maskCanvas.getContext('2d');

  if (blendStart > 0) {
    maskCtx.fillStyle = 'white';
    maskCtx.fillRect(0, 0, docWidth, blendStart);
  }
  if (blendEnd > blendStart) {
    const gradient = maskCtx.createLinearGradient(0, blendStart, 0, blendEnd);
    gradient.addColorStop(0, 'white');
    gradient.addColorStop(1, 'rgba(255,255,255,0)');
    maskCtx.fillStyle = gradient;
    maskCtx.fillRect(0, blendStart, docWidth, blendEnd - blendStart);
  }

  upperCtx.globalCompositeOperation = 'destination-in';
  upperCtx.drawImage(maskCanvas, 0, 0);

  resultCtx.drawImage(lowerCanvas, 0, 0);
  resultCtx.drawImage(upperCanvas, 0, 0);

  return resultCanvas;
}

function computeAffineForward(srcPts, dstPts) {
  if (srcPts.length < 3 || dstPts.length < 3) return null;
  const n = Math.min(srcPts.length, dstPts.length);

  function solveLeastSquares(A, b) {
    const At = numericTranspose(A);
    const AtA = numericMultiply(At, A);
    const Atb = numericMultiply(At, b.map(v => [v]));
    return numericSolve(AtA, Atb.map(v => v[0]));
  }

  function numericTranspose(m) {
    return m[0].map((_, col) => m.map(row => row[col]));
  }

  function numericMultiply(a, b) {
    const result = [];
    for (let i = 0; i < a.length; i++) {
      result[i] = [];
      for (let j = 0; j < b[0].length; j++) {
        let sum = 0;
        for (let k = 0; k < a[0].length; k++) {
          sum += a[i][k] * b[k][j];
        }
        result[i][j] = sum;
      }
    }
    return result;
  }

  function numericSolve(A, b) {
    const n = A.length;
    const aug = A.map((row, i) => [...row, b[i]]);
    for (let col = 0; col < n; col++) {
      let maxRow = col;
      for (let row = col + 1; row < n; row++) {
        if (Math.abs(aug[row][col]) > Math.abs(aug[maxRow][col])) maxRow = row;
      }
      [aug[col], aug[maxRow]] = [aug[maxRow], aug[col]];
      for (let row = col + 1; row < n; row++) {
        const factor = aug[row][col] / aug[col][col];
        for (let j = col; j <= n; j++) aug[row][j] -= factor * aug[col][j];
      }
    }
    const x = new Array(n);
    for (let i = n - 1; i >= 0; i--) {
      x[i] = aug[i][n] / aug[i][i];
      for (let j = i - 1; j >= 0; j--) aug[j][n] -= aug[j][i] * x[i];
    }
    return x;
  }

  const A = [];
  const b = [];

  // Canvas setTransform(a,b,c,d,e,f) maps (srcX, srcY) to:
  //   dstX = a * srcX + c * srcY + e
  //   dstY = b * srcX + d * srcY + f
  //
  // Solve for params [a, b, c, d, e, f] such that:
  // For each (src, dst) pair:
  //   dst_x = a*src_x + c*src_y + e
  //   dst_y = b*src_x + d*src_y + f

  for (let i = 0; i < n; i++) {
    const s = srcPts[i];
    const d = dstPts[i];
    // dst_x = a*src_x + 0*src_y + 0*??? + c*src_y + 0*??? + e
    // Actually canvas order is: (a, b, c, d, e, f) with:
    //   newX = a*oldX + c*oldY + e
    //   newY = b*oldX + d*oldY + f
    // So params are [a, b, c, d, e, f]
    // dst_x = a*src_x + c*src_y + e → row: [src_x, 0, src_y, 0, 1, 0]
    // dst_y = b*src_x + d*src_y + f → row: [0, src_x, 0, src_y, 0, 1]
    A.push([s[0], 0, s[1], 0, 1, 0]);
    A.push([0, s[0], 0, s[1], 0, 1]);
    b.push(d[0]);
    b.push(d[1]);
  }

  const params = solveLeastSquares(A, b);
  if (!params || params.length < 6) return null;
  return params;
}

async function runSmartFit(targetContainer) {
  const selectIngestSlot = document.getElementById('select-ingest-slot');
  const category = selectIngestSlot ? selectIngestSlot.value : 'topwear';

  const docWidth = DOLL_CONFIG.canvas.width || 768;
  const docHeight = DOLL_CONFIG.canvas.height || 768;

  const srcCanvas = document.createElement('canvas');
  srcCanvas.width = docWidth;
  srcCanvas.height = docHeight;
  const srcCtx = srcCanvas.getContext('2d');

  srcCtx.translate(docWidth / 2 + alignSettings.x, docHeight / 2 + alignSettings.y);
  srcCtx.scale(alignSettings.scaleX, alignSettings.scaleY);
  srcCtx.translate(-docWidth / 2, -docHeight / 2);
  srcCtx.drawImage(pendingAssetImage, 0, 0, docWidth, docHeight);

  inferredAnchors = inferGarmentAnchorsJS(srcCanvas);
  console.log('Inferred anchors:', inferredAnchors);

  if (Object.keys(inferredAnchors).length < 3) {
    alert('Could not detect garment landmarks. Make sure the garment is visible on a transparent background.');
    return;
  }

  const requiredManual = MANUAL_PLACE_ANCHORS[category.toLowerCase()] || [];
  pendingPlacementQueue = requiredManual.filter(n => !(n in inferredAnchors));

  drawAnchorOverlay(inferredAnchors);

  const rigAnchors = getRigAnchorsForCategory(category);
  const params = computeFitParams(inferredAnchors, category, rigAnchors);
  const { upperParams, lowerParams } = params;

  if (!upperParams && !lowerParams) {
    alert('Not enough matching anchor points for fitting. Need at least 3.');
    return;
  }

  fittedCanvas = applyPiecewiseBlend(docWidth, docHeight, srcCanvas, params);

  const btnToggle = document.getElementById('btn-toggle-fit-preview');
  if (btnToggle) {
    btnToggle.style.display = 'inline-block';
    btnToggle.textContent = 'Show Raw';
    btnToggle.dataset.showing = 'fitted';
  }

  const fitStatus = document.getElementById('fit-status');
  if (fitStatus) {
    fitStatus.style.display = 'block';
    if (hasPendingPlacements()) {
      fitStatus.innerHTML = `Click on the garment to place: <strong>${pendingPlacementQueue[0]}</strong> (${pendingPlacementQueue.length} remaining)`;
    } else {
      const anchorCount = Object.keys(inferredAnchors).length;
      fitStatus.innerHTML = `Fit applied: ${anchorCount} anchors, ${params.upperSrc.length + params.lowerSrc.length} matched points <button class="btn btn-sm" onclick="document.getElementById('fit-status').style.display='none'">Dismiss</button>`;
    }
  }

  renderFitOverlay(targetContainer, true);
}

let dragAnchorName = null;
let dragOffsetX = 0;
let dragOffsetY = 0;
let anchorDragAnchors = null;
let dragListeners = null;

function clearAnchorDrag() {
  dragAnchorName = null;
  anchorDragAnchors = null;
  if (dragListeners) {
    const { canvas, onDown, onMove, onUp } = dragListeners;
    canvas.removeEventListener('mousedown', onDown);
    window.removeEventListener('mousemove', onMove);
    window.removeEventListener('mouseup', onUp);
    dragListeners = null;
  }
}

function getCanvasCoords(canvas, e) {
  const rect = canvas.getBoundingClientRect();
  const scaleX = canvas.width / rect.width;
  const scaleY = canvas.height / rect.height;
  return {
    x: (e.clientX - rect.left) * scaleX,
    y: (e.clientY - rect.top) * scaleY,
  };
}

function wireAnchorDrag(canvas, anchors) {
  clearAnchorDrag();
  anchorDragAnchors = anchors;

  function onDown(e) {
    if (hasPendingPlacements()) {
      const coords = getCanvasCoords(canvas, e);
      const name = pendingPlacementQueue[0];
      anchors[name] = [Math.round(coords.x), Math.round(coords.y)];
      pendingPlacementQueue.shift();
      drawAnchorOverlay(anchors, true);
      updatePlacementStatus();
      e.preventDefault();
      return;
    }
    if (!anchorsEnabled) return;
    const coords = getCanvasCoords(canvas, e);
    const name = findNearestAnchor(coords.x, coords.y);
    if (name) {
      dragAnchorName = name;
      dragOffsetX = coords.x - anchors[name][0];
      dragOffsetY = coords.y - anchors[name][1];
      canvas.style.cursor = 'grabbing';
      e.preventDefault();
    }
  }

  function onMove(e) {
    if (!anchorsEnabled && !dragAnchorName) return;
    if (!dragAnchorName) {
      const coords = getCanvasCoords(canvas, e);
      const name = findNearestAnchor(coords.x, coords.y);
      canvas.style.cursor = name ? 'grab' : 'default';
      return;
    }
    const coords = getCanvasCoords(canvas, e);
    anchors[dragAnchorName][0] = Math.round(coords.x - dragOffsetX);
    anchors[dragAnchorName][1] = Math.round(coords.y - dragOffsetY);

    drawAnchorOverlay(anchors, true);
  }

  function onUp(e) {
    if (dragAnchorName) {
      dragAnchorName = null;
      canvas.style.cursor = 'default';
      reapplyFit();
    }
  }

  canvas.addEventListener('mousedown', onDown);
  window.addEventListener('mousemove', onMove);
  window.addEventListener('mouseup', onUp);
  dragListeners = { canvas, onDown, onMove, onUp };
}

function findNearestAnchor(cx, cy, threshold) {
  threshold = threshold || 20;
  const anchors = anchorDragAnchors;
  if (!anchors) return null;
  let nearest = null;
  let nearestDist = threshold;
  for (const [name, [ax, ay]] of Object.entries(anchors)) {
    const dx = cx - ax;
    const dy = cy - ay;
    const dist = Math.sqrt(dx * dx + dy * dy);
    if (dist < nearestDist) {
      nearestDist = dist;
      nearest = name;
    }
  }
  return nearest;
}

function reapplyFit() {
  const docWidth = DOLL_CONFIG.canvas.width || 768;
  const docHeight = DOLL_CONFIG.canvas.height || 768;
  const selectIngestSlot = document.getElementById('select-ingest-slot');
  const category = selectIngestSlot ? selectIngestSlot.value : 'topwear';
  const rigAnchors = getRigAnchorsForCategory(category);

  if (Object.keys(inferredAnchors).length < 3) return;

  const params = computeFitParams(inferredAnchors, category, rigAnchors);
  const { upperParams, lowerParams } = params;
  if (!upperParams && !lowerParams) return;

  const srcCanvas = document.createElement('canvas');
  srcCanvas.width = docWidth;
  srcCanvas.height = docHeight;
  const srcCtx2 = srcCanvas.getContext('2d');
  srcCtx2.translate(docWidth / 2 + alignSettings.x, docHeight / 2 + alignSettings.y);
  srcCtx2.scale(alignSettings.scaleX, alignSettings.scaleY);
  srcCtx2.translate(-docWidth / 2, -docHeight / 2);
  srcCtx2.drawImage(pendingAssetImage, 0, 0, docWidth, docHeight);

  fittedCanvas = applyPiecewiseBlend(docWidth, docHeight, srcCanvas, params);

  const targetContainer = document.getElementById('doll-layers-target');
  if (targetContainer) renderFitOverlay(targetContainer, !document.getElementById('btn-toggle-fit-preview') || document.getElementById('btn-toggle-fit-preview').dataset.showing === 'fitted');
}

function drawAnchorOverlay(anchors, skipWire) {
  const overlayCanvas = document.getElementById('anchor-overlay-canvas');
  if (!overlayCanvas) return;
  overlayCanvas.style.display = 'block';
  const ctx = overlayCanvas.getContext('2d');
  const w = overlayCanvas.width;
  const h = overlayCanvas.height;
  ctx.clearRect(0, 0, w, h);

  const colors = {
    neck: '#ff0000',
    left_shoulder: '#00ff00', right_shoulder: '#00ff00',
    strap_left: '#aaff00', strap_right: '#aaff00',
    bust_left: '#ff66cc', bust_right: '#ff66cc',
    waist_left: '#ffff00', waist_right: '#ffff00',
    hip_left: '#ff00ff', hip_right: '#ff00ff',
    hem_left: '#00ffff', hem_right: '#00ffff',
    knee_left: '#ff8800', knee_right: '#ff8800',
  };

  for (const [name, [x, y]] of Object.entries(anchors)) {
    const color = colors[name] || '#ffffff';
    ctx.fillStyle = color;
    ctx.beginPath();
    ctx.arc(x, y, 5, 0, Math.PI * 2);
    ctx.fill();
    ctx.strokeStyle = '#000000';
    ctx.lineWidth = 1.5;
    ctx.stroke();
    ctx.fillStyle = '#ffffff';
    ctx.font = '10px monospace';
    ctx.fillText(name, x + 8, y + 4);
  }

  if (!skipWire) {
    wireAnchorDrag(overlayCanvas, anchors);
    const pointerOn = anchorsEnabled || hasPendingPlacements();
    const btn = document.getElementById('btn-toggle-anchor-edit');
    if (btn) {
      btn.style.display = 'block';
      btn.textContent = anchorsEnabled ? '🔒 Anchor Edit: ON' : '🔓 Anchor Edit: OFF';
      overlayCanvas.style.pointerEvents = pointerOn ? 'auto' : 'none';
    }
    const confirmBtn = document.getElementById('btn-confirm-anchors');
    if (confirmBtn) {
      confirmBtn.style.display = 'block';
      confirmBtn.textContent = '✅ Confirm Anchors';
      confirmBtn.style.borderColor = '';
      confirmBtn.style.color = '';
      confirmBtn.disabled = hasPendingPlacements();
    }
    const submitBtn = document.getElementById('btn-ingest-submit');
    if (submitBtn) submitBtn.disabled = true;
  }
}

function toggleFitPreview(targetContainer) {
  const btn = document.getElementById('btn-toggle-fit-preview');
  if (!btn) return;
  const showing = btn.dataset.showing || 'fitted';
  const newShowing = showing === 'fitted' ? 'raw' : 'fitted';
  btn.dataset.showing = newShowing;
  btn.textContent = newShowing === 'fitted' ? 'Show Raw' : 'Show Fitted';
  renderFitOverlay(targetContainer, newShowing === 'fitted');
}

function renderFitOverlay(targetContainer, showFitted) {
  const overlayContainer = document.getElementById('fit-overlay-container');
  if (!overlayContainer) {
    const container = document.createElement('div');
    container.id = 'fit-overlay-container';
    container.style.cssText = 'position:absolute;top:0;left:0;width:100%;height:100%;pointer-events:none;z-index:250;';
    const target = document.getElementById('doll-layers-target');
    if (target) target.appendChild(container);
  }

  const container = document.getElementById('fit-overlay-container');
  if (!container) return;

  container.innerHTML = '';

  const img = document.createElement('img');
  if (showFitted && fittedCanvas) {
    img.src = fittedCanvas.toDataURL();
  } else {
    return;
  }
  img.style.cssText = 'width:100%;height:100%;object-fit:contain;opacity:0.6;';
  container.appendChild(img);
}

export function getFittedCanvas() {
  return fittedCanvas;
}

export function clearFitPreview() {
  clearAnchorDrag();
  fittedCanvas = null;
  inferredAnchors = {};
  confirmedAnchors = null;
  pendingPlacementQueue = [];
  const container = document.getElementById('fit-overlay-container');
  if (container) container.innerHTML = '';
  const btn = document.getElementById('btn-toggle-fit-preview');
  if (btn) btn.style.display = 'none';
  const overlay = document.getElementById('anchor-overlay-canvas');
  if (overlay) {
    overlay.style.display = 'none';
    overlay.style.pointerEvents = 'none';
    const ctx = overlay.getContext('2d');
    ctx.clearRect(0, 0, overlay.width, overlay.height);
  }
  const status = document.getElementById('fit-status');
  if (status) status.style.display = 'none';
  const anchorBtn = document.getElementById('btn-toggle-anchor-edit');
  if (anchorBtn) {
    anchorBtn.style.display = 'none';
    anchorBtn.textContent = '🔓 Anchor Edit: OFF';
  }
  const confirmBtn = document.getElementById('btn-confirm-anchors');
  if (confirmBtn) {
    confirmBtn.style.display = 'none';
    confirmBtn.textContent = '✅ Confirm Anchors';
    confirmBtn.style.borderColor = '';
    confirmBtn.style.color = '';
    confirmBtn.disabled = false;
  }
  anchorsEnabled = false;
}
