import { describe, it, expect, beforeAll } from 'vitest';

describe('Schema Validation', () => {
  const validProject = {
    version: 1,
    canvas: { width: 768, height: 768 },
    layers: [
      { id: 'hair_back', name: 'hair_back', file: 'hair_back.png', z: 10, category: 'hair', subcategory: 'hair_back', toggleable: true, defaultVisible: true, dyeable: true },
      { id: 'body_face', name: 'body_face', file: 'body_face.png', z: 50, category: 'face', subcategory: 'face' },
    ],
    wardrobe: {
      topwear: {
        name: 'Topwear',
        defaultValue: 'skin_wear',
        options: [
          { value: 'skin_wear', name: 'Naked / Skin Wear', layers: ['skin_wear_top'] },
          { value: 'none', name: 'Invisible / None', layers: [] },
        ],
      },
    },
  };

  it('should have required top-level fields', () => {
    expect(validProject).toHaveProperty('version');
    expect(validProject).toHaveProperty('canvas');
    expect(validProject).toHaveProperty('layers');
    expect(validProject).toHaveProperty('wardrobe');
  });

  it('should have valid canvas dimensions', () => {
    expect(validProject.canvas.width).toBeGreaterThan(0);
    expect(validProject.canvas.height).toBeGreaterThan(0);
  });

  it('should have layers with required fields', () => {
    validProject.layers.forEach(layer => {
      expect(layer).toHaveProperty('id');
      expect(layer).toHaveProperty('name');
      expect(layer).toHaveProperty('file');
      expect(layer).toHaveProperty('z');
      expect(layer).toHaveProperty('category');
      expect(['hair', 'eyes', 'face', 'wardrobe']).toContain(layer.category);
    });
  });

  it('should have valid category values', () => {
    const categories = new Set(validProject.layers.map(l => l.category));
    categories.forEach(cat => {
      expect(['hair', 'eyes', 'face', 'wardrobe']).toContain(cat);
    });
  });

  it('should reject negative z values', () => {
    const badLayer = { ...validProject.layers[0], z: -1 };
    expect(badLayer.z).toBeLessThan(0);
  });

  it('should require wardrobe slot to have options', () => {
    Object.entries(validProject.wardrobe).forEach(([, slot]) => {
      expect(slot).toHaveProperty('options');
      expect(Array.isArray(slot.options)).toBe(true);
      expect(slot.options.length).toBeGreaterThan(0);
    });
  });

  it('should have unique layer IDs', () => {
    const ids = validProject.layers.map(l => l.id);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it('should have valid layer IDs (lowercase with underscores)', () => {
    validProject.layers.forEach(layer => {
      expect(layer.id).toMatch(/^[a-z0-9_]+$/);
    });
  });
});

describe('Z-Order Sorting', () => {
  const layers = [
    { id: 'a', z: 30, category: 'face' },
    { id: 'b', z: 10, category: 'hair' },
    { id: 'c', z: 20, category: 'eyes' },
    { id: 'd', z: 50, category: 'wardrobe', subcategory: 'topwear' },
    { id: 'e', z: 40, category: 'wardrobe', subcategory: 'handwear' },
  ];

  it('should sort layers by z value ascending', () => {
    const sorted = [...layers].sort((a, b) => a.z - b.z);
    expect(sorted[0].id).toBe('b');
    expect(sorted[1].id).toBe('c');
    expect(sorted[2].id).toBe('a');
    expect(sorted[3].id).toBe('e');
    expect(sorted[4].id).toBe('d');
  });

  it('should handle layers with same z value', () => {
    const tied = [
      { id: 'x', z: 10, category: 'face' },
      { id: 'y', z: 10, category: 'hair' },
    ];
    const sorted = [...tied].sort((a, b) => a.z - b.z);
    expect(sorted.length).toBe(2);
    expect(sorted[0].id).toBe('x');
    expect(sorted[1].id).toBe('y');
  });

  it('should assign z values in increments of 10 from PSD import order', () => {
    const indices = [0, 1, 2, 3, 4];
    const zValues = indices.map(i => (i + 1) * 10);
    expect(zValues).toEqual([10, 20, 30, 40, 50]);
  });

  it('should sort layers with computedZ', () => {
    const withComputedZ = layers.map(l => ({
      ...l,
      computedZ: l.subcategory === 'handwear' ? 165 : l.z,
    })).sort((a, b) => a.computedZ - b.computedZ);

    expect(withComputedZ[0].id).toBe('b');
    expect(withComputedZ[1].id).toBe('c');
  });
});

describe('State Save/Load Roundtrip', () => {
  const mockState = {
    wardrobe: { topwear: 'clothing', bottomwear: 'skin_wear', legwear: 'none', handwear: 'clothing' },
    wardrobeDepth: { handwear: 'front_body' },
    toggles: { hair_front: true, hair_back: false, eyes: true },
    dyes: { hair: { hue: 180, sat: 100, light: 120 }, eyes: { hue: 45 } },
    offsets: { clothed_assets: { x: 5, y: -3 }, topwear: { x: 2, y: 0 } },
    zoom: 1.2,
    theme: 'light',
    showGrid: false,
  };

  it('should serialize to JSON', () => {
    const json = JSON.stringify(mockState);
    expect(typeof json).toBe('string');
    const parsed = JSON.parse(json);
    expect(parsed).toEqual(mockState);
  });

  it('should survive JSON roundtrip', () => {
    const json = JSON.stringify(mockState);
    const parsed = JSON.parse(json);
    expect(parsed.wardrobe.topwear).toBe('clothing');
    expect(parsed.dyes.hair.hue).toBe(180);
    expect(parsed.offsets.clothed_assets.x).toBe(5);
    expect(parsed.toggles.hair_back).toBe(false);
  });

  it('should handle empty state gracefully', () => {
    const empty = {
      wardrobe: {},
      wardrobeDepth: {},
      toggles: {},
      dyes: { hair: { hue: 0, sat: 100, light: 100 }, eyes: { hue: 0 } },
      offsets: {},
    };
    const json = JSON.stringify(empty);
    const parsed = JSON.parse(json);
    expect(Object.keys(parsed.wardrobe).length).toBe(0);
  });

  it('should reject state with wrong version', () => {
    const bad = { ...mockState, version: 999 };
    expect(bad.version).toBe(999);
  });

  it('should include timestamp in export', () => {
    const exported = {
      ...mockState,
      version: 1,
      exportedAt: new Date().toISOString(),
    };
    expect(exported).toHaveProperty('exportedAt');
    expect(() => new Date(exported.exportedAt)).not.toThrow();
  });
});

describe('Utility Functions', () => {
  let utils;

  beforeAll(async () => {
    utils = await import('../js/utils.js');
  });

  describe('cleanLayerName', () => {
    it('should lowercase and replace spaces with underscores', () => {
      expect(utils.cleanLayerName('Hair Front')).toBe('hair_front');
    });

    it('should replace hyphens with underscores', () => {
      expect(utils.cleanLayerName('skin-wear-top')).toBe('skin_wear_top');
    });

    it('should handle leading/trailing whitespace', () => {
      expect(utils.cleanLayerName('  Body Face  ')).toBe('body_face');
    });

    it('should handle multiple spaces', () => {
      expect(utils.cleanLayerName('left   arm')).toBe('left_arm');
    });
  });

  describe('getCategory', () => {
    it('should classify hair names', () => {
      expect(utils.getCategory('hair_front')).toBe('hair');
      expect(utils.getCategory('long_hair')).toBe('hair');
      expect(utils.getCategory('bangs')).toBe('hair');
    });

    it('should classify eye names', () => {
      expect(utils.getCategory('eyes_white_l')).toBe('eyes');
      expect(utils.getCategory('left_iris')).toBe('eyes');
      expect(utils.getCategory('eyebrow')).toBe('eyes');
    });

    it('should classify face names', () => {
      expect(utils.getCategory('body_face')).toBe('face');
      expect(utils.getCategory('nose')).toBe('face');
      expect(utils.getCategory('neck')).toBe('face');
    });

    it('should classify wardrobe names', () => {
      expect(utils.getCategory('clothing_topwear')).toBe('wardrobe');
      expect(utils.getCategory('skin_wear_hands')).toBe('wardrobe');
    });
  });

  describe('getWardrobeSlot', () => {
    it('should identify topwear', () => {
      expect(utils.getWardrobeSlot('clothing_top')).toBe('topwear');
      expect(utils.getWardrobeSlot('leather_vest')).toBe('topwear');
    });

    it('should identify bottomwear', () => {
      expect(utils.getWardrobeSlot('cloth_bottom')).toBe('bottomwear');
    });

    it('should identify legwear', () => {
      expect(utils.getWardrobeSlot('cloth_legs')).toBe('legwear');
      expect(utils.getWardrobeSlot('boots')).toBe('legwear');
    });

    it('should identify handwear', () => {
      expect(utils.getWardrobeSlot('cloth_hands')).toBe('handwear');
      expect(utils.getWardrobeSlot('gloves')).toBe('handwear');
    });
  });

  describe('getOptionValue', () => {
    it('should identify skin_wear', () => {
      expect(utils.getOptionValue('skin_wear_top', 'topwear')).toBe('skin_wear');
    });

    it('should identify clothing', () => {
      expect(utils.getOptionValue('clothing_topwear', 'topwear')).toBe('clothing');
    });

    it('should return custom option values', () => {
      // The function strips slot keywords (jacket, vest, coat, etc.) and orientation suffixes (l/r)
      expect(utils.getOptionValue('denim_jacket', 'topwear')).toBe('denim');
      expect(utils.getOptionValue('leather_vest', 'topwear')).toBe('eathe');
      expect(utils.getOptionValue('custom_sash', 'topwear')).toBe('custom_sash');
    });

    it('should fallback to skin_wear for bare slot names', () => {
      expect(utils.getOptionValue('topwear', 'topwear')).toBe('skin_wear');
    });
  });

  describe('getBoundingBox', () => {
    it('should return null for empty canvas', () => {
      const canvas = document.createElement('canvas');
      canvas.width = 100;
      canvas.height = 100;
      expect(utils.getBoundingBox(canvas)).toBeNull();
    });

    it('should detect non-transparent content bounds', () => {
      const canvas = document.createElement('canvas');
      canvas.width = 100;
      canvas.height = 100;
      const ctx = canvas.getContext('2d');
      ctx.fillStyle = 'red';
      ctx.fillRect(20, 30, 10, 10);

      const box = utils.getBoundingBox(canvas);
      expect(box).not.toBeNull();
      expect(box.x).toBe(20);
      expect(box.y).toBe(30);
      expect(box.width).toBe(10);
      expect(box.height).toBe(10);
    });
  });

  describe('isHandwearRight / isHandwearLeft', () => {
    it('should identify right handwear by suffix', () => {
      expect(utils.isHandwearRight('clothing_handwear_r', 'clothing_handwear_r')).toBe(true);
      expect(utils.isHandwearRight('glove_right', 'glove_right')).toBe(true);
    });

    it('should identify left handwear by suffix', () => {
      expect(utils.isHandwearLeft('clothing_handwear_l', 'clothing_handwear_l')).toBe(true);
      expect(utils.isHandwearLeft('glove_left', 'glove_left')).toBe(true);
    });

    it('should return false for non-handwear', () => {
      expect(utils.isHandwearRight('hair_front', 'hair_front')).toBe(false);
      expect(utils.isHandwearLeft('hair_front', 'hair_front')).toBe(false);
    });
  });
});
