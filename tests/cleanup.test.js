import { describe, expect, it } from 'vitest';
import {
  applyAlphaThreshold,
  countVisibleMaskOverlap,
  getAlphaStats,
  keepLargestConnectedComponent,
  parseHexColor,
  removeColorKey,
  removeSmallIslands,
  removeWhiteBackground,
} from '../js/cleanup.js';

function imageData(width, height, fill = [0, 0, 0, 0]) {
  const data = new Uint8ClampedArray(width * height * 4);
  for (let i = 0; i < data.length; i += 4) {
    data.set(fill, i);
  }
  return { data, width, height };
}

function setPixel(img, x, y, rgba) {
  const i = (y * img.width + x) * 4;
  img.data.set(rgba, i);
}

describe('cleanup utilities', () => {
  it('parses hex colors', () => {
    expect(parseHexColor('#ff8800')).toEqual([255, 136, 0]);
    expect(parseHexColor('nonsense')).toEqual([255, 255, 255]);
  });

  it('removes white backgrounds by alpha', () => {
    const img = imageData(2, 1, [255, 255, 255, 255]);
    setPixel(img, 1, 0, [30, 40, 50, 255]);
    const out = removeWhiteBackground(img, 5);
    expect(out.data[3]).toBe(0);
    expect(out.data[7]).toBe(255);
  });

  it('removes picked color backgrounds', () => {
    const img = imageData(2, 1, [0, 255, 0, 255]);
    setPixel(img, 1, 0, [200, 0, 0, 255]);
    const out = removeColorKey(img, [0, 255, 0], 10);
    expect(out.data[3]).toBe(0);
    expect(out.data[7]).toBe(255);
  });

  it('applies alpha threshold', () => {
    const img = imageData(2, 1, [0, 0, 0, 0]);
    setPixel(img, 0, 0, [1, 1, 1, 80]);
    setPixel(img, 1, 0, [1, 1, 1, 180]);
    const out = applyAlphaThreshold(img, 128);
    expect(out.data[3]).toBe(0);
    expect(out.data[7]).toBe(255);
  });

  it('keeps largest connected component', () => {
    const img = imageData(5, 1);
    setPixel(img, 0, 0, [1, 1, 1, 255]);
    setPixel(img, 2, 0, [1, 1, 1, 255]);
    setPixel(img, 3, 0, [1, 1, 1, 255]);
    const out = keepLargestConnectedComponent(img);
    expect(out.data[3]).toBe(0);
    expect(out.data[11]).toBe(255);
    expect(out.data[15]).toBe(255);
  });

  it('removes small islands below area threshold', () => {
    const img = imageData(5, 1);
    setPixel(img, 0, 0, [1, 1, 1, 255]);
    setPixel(img, 2, 0, [1, 1, 1, 255]);
    setPixel(img, 3, 0, [1, 1, 1, 255]);
    const out = removeSmallIslands(img, 2);
    expect(out.data[3]).toBe(0);
    expect(out.data[11]).toBe(255);
    expect(out.data[15]).toBe(255);
  });

  it('reports alpha coverage and mask overlap', () => {
    const img = imageData(2, 2);
    setPixel(img, 0, 0, [1, 1, 1, 255]);
    setPixel(img, 1, 0, [1, 1, 1, 255]);
    const mask = imageData(2, 2);
    setPixel(mask, 1, 0, [0, 0, 0, 255]);
    const stats = getAlphaStats(img);
    const overlap = countVisibleMaskOverlap(img, mask);
    expect(stats.coverage).toBe(0.5);
    expect(overlap).toEqual({ overlap: 1, visible: 2 });
  });
});
