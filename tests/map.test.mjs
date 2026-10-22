import { test } from 'node:test';
import assert from 'node:assert/strict';
import { fitViewport } from '../web/map-viewport.js';

test('new monitoring rectangle fits completely with map padding', () => {
  const { z, bounds, corner } = fitViewport([137.30809, 34.69886, 137.34545, 34.74863]);
  assert.equal(z, 13);
  for (const [x, y] of bounds) {
    assert(x - corner[0] >= 30 && x - corner[0] <= 870);
    assert(y - corner[1] >= 30 && y - corner[1] <= 590);
  }
});

test('original smaller rectangle retains detail and invalid bounds fail', () => {
  assert.equal(fitViewport([137.285, 34.717, 137.320, 34.744]).z, 14);
  for (const bbox of [[1, 2, 0, 3], [1, 3, 2, 2], [1, 2, 3, NaN], [1, 2, 3], [1, 2, 3, 90]])
    assert.throws(() => fitViewport(bbox));
});
