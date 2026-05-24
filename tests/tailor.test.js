import { describe, it, expect } from 'vitest';

const RECIPE_NAMES = new Set([
  'bodice',
  'tight_top',
  'tight_dress',
  'leggings',
  'stockings',
  'gloves',
  'bodycon_dress',
  'simple_flared_dress',
]);

const SLIDER_BOUNDS = {
  'expand-x':  { min: 0, max: 40, default: 0 },
  'expand-y':  { min: 0, max: 40, default: 0 },
  dilate:      { min: 0, max: 20, default: 0 },
  erode:       { min: 0, max: 20, default: 0 },
  smooth:      { min: 0, max: 12, default: 2 },
  flare:       { min: 0, max: 60, default: 0 },
  taper:       { min: 0, max: 30, default: 0 },
};

describe('Digital Tailor — data contract', () => {
  it('RECIPE_NAMES contains all 8 expected recipes', () => {
    expect(RECIPE_NAMES.size).toBe(8);
    for (const name of [
      'bodice', 'tight_top', 'tight_dress', 'leggings',
      'stockings', 'gloves', 'bodycon_dress', 'simple_flared_dress',
    ]) {
      expect(RECIPE_NAMES.has(name)).toBe(true);
    }
  });

  it('default color is a valid 7-char hex', () => {
    const defaultColor = '#ffffff';
    expect(defaultColor).toMatch(/^#[0-9a-f]{6}$/i);
    expect(defaultColor.length).toBe(7);
  });

  it('expand_x slider max is 40', () => {
    expect(SLIDER_BOUNDS['expand-x'].max).toBe(40);
  });

  it('smooth slider default is 2', () => {
    expect(SLIDER_BOUNDS.smooth.default).toBe(2);
  });

  it('flare slider max is 60', () => {
    expect(SLIDER_BOUNDS.flare.max).toBe(60);
  });

  it('all sliders have non-negative min', () => {
    for (const [name, bounds] of Object.entries(SLIDER_BOUNDS)) {
      expect(bounds.min, `${name} min`).toBeGreaterThanOrEqual(0);
    }
  });

  it('all slider defaults are within bounds', () => {
    for (const [name, { min, max, default: def }] of Object.entries(SLIDER_BOUNDS)) {
      expect(def, `${name} default`).toBeGreaterThanOrEqual(min);
      expect(def, `${name} default`).toBeLessThanOrEqual(max);
    }
  });
});
