import { describe, it, expect } from 'vitest';
import { computeBakeGeometry } from '../js/utils.js';

const identity = { x: 0, y: 0, scaleX: 1, scaleY: 1 };

describe('computeBakeGeometry', () => {
  it('centers a non-square source at canvas center under identity alignment', () => {
    const g = computeBakeGeometry(200, 300, 768, 768, identity);
    expect(g).toEqual({ left: 284, top: 234, width: 200, height: 300 });
  });

  it('applies translation and non-uniform scale', () => {
    const align = { x: 50, y: -10, scaleX: 2, scaleY: 0.5 };
    const g = computeBakeGeometry(200, 300, 768, 768, align);
    expect(g.width).toBe(400);
    expect(g.height).toBe(150);
    expect(g.left).toBe(768 / 2 + 50 - 400 / 2);
    expect(g.top).toBe(768 / 2 - 10 - 150 / 2);
  });

  it('auto-shrink: oversized source contained within canvas', () => {
    const imgW = 1200;
    const imgH = 900;
    const docW = 768;
    const docH = 768;
    const fit = Math.min(1.0, docW / imgW, docH / imgH);
    const g = computeBakeGeometry(imgW, imgH, docW, docH, { x: 0, y: 0, scaleX: fit, scaleY: fit });
    expect(g.width).toBeCloseTo(imgW * fit, 6);
    expect(g.height).toBeCloseTo(imgH * fit, 6);
    expect(g.left + g.width / 2).toBeCloseTo(docW / 2, 6);
    expect(g.top + g.height / 2).toBeCloseTo(docH / 2, 6);
    expect(g.width).toBeLessThanOrEqual(docW);
    expect(g.height).toBeLessThanOrEqual(docH);
  });

  it('renders a small accessory at native size, centered', () => {
    const g = computeBakeGeometry(50, 50, 768, 768, identity);
    expect(g.width).toBe(50);
    expect(g.height).toBe(50);
    expect(g.left).toBe(384 - 25);
    expect(g.top).toBe(384 - 25);
  });

  it('multiplicative wheel preserves aspect ratio across both axes', () => {
    const before = { x: 0, y: 0, scaleX: 1.5, scaleY: 1.0 };
    const factor = 1.02;
    const after = { x: 0, y: 0, scaleX: 1.5 * factor, scaleY: 1.0 * factor };
    const g1 = computeBakeGeometry(200, 300, 768, 768, before);
    const g2 = computeBakeGeometry(200, 300, 768, 768, after);
    expect(g1.width / g1.height).toBeCloseTo(g2.width / g2.height, 10);
  });

  it('non-zero translation moves the bbox without resizing it', () => {
    const g0 = computeBakeGeometry(200, 200, 768, 768, identity);
    const g1 = computeBakeGeometry(200, 200, 768, 768, { x: 30, y: -40, scaleX: 1, scaleY: 1 });
    expect(g1.width).toBe(g0.width);
    expect(g1.height).toBe(g0.height);
    expect(g1.left - g0.left).toBe(30);
    expect(g1.top - g0.top).toBe(-40);
  });
});
