const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
class Element {
  constructor() { this.children = []; this.style = {}; this.textContent = ''; this.hidden = false; }
  append(child) { this.children.push(child); }
  replaceChildren(...children) { this.children = children; }
}
const scope = new Element(), list = new Element(), status = new Element();
const observation = {ageSeconds: 0, radiusNm: 25, center: {latitude: 0, longitude: 0}, aircraft: [
  {callsign: '<TEST>', typeName: 'Boeing 737-800', latitude: 0, longitude: 0,
   groundSpeedKnots: 360, trackDegrees: 90, altitudeFeet: 10000, originName: 'Köln/Bonn', destinationName: 'London Heathrow'},
  {callsign: 'UNKNOWN', latitude: 0, longitude: 0.01, altitudeFeet: null, groundSpeedKnots: null, trackDegrees: null}
]};
const card = new Element();
card.querySelector = selector => ({'[data-aircraft-snapshot]': {textContent: JSON.stringify(observation)},
  '[data-aircraft-list]': list, '[data-aircraft-scope]': scope, '[data-aircraft-status]': status})[selector];
let now = 0, fetches = 0;
const timers = new Map();
const context = {document: {currentScript: {dataset: {aircraftUrl: '/aircraft'}},
  querySelector: () => card, createElement: () => new Element()},
  performance: {now: () => now}, Date,
  MutationObserver: class { observe() {} },
  fetch: async () => { fetches++; return {ok: false}; },
  setInterval: (fn, ms) => timers.set(ms, fn)};
vm.runInNewContext(fs.readFileSync('app/static/aircraft-preview.js', 'utf8'), context);
const copy = () => list.children[0].children.map(element => element.textContent).join('\n');
assert(copy().includes('Boeing 737-800'));
assert(copy().includes('3048 m'));
assert(copy().includes('667 km/h'));
assert(copy().includes('Köln/Bonn'));
assert(copy().includes('<TEST>'));
const initial = parseFloat(scope.children[0].style.left);
now = 2000; timers.get(2000)();
assert(parseFloat(scope.children[0].style.left) > initial);
assert(copy().includes('0.4 km'));
now = 120000; timers.get(2000)();
const frozen = scope.children[0].style.left;
now = 240000; timers.get(2000)();
assert.equal(scope.children[0].style.left, frozen);
assert(status.textContent.includes('Alte Position'));
const button = list.children[1];
button.onclick();
assert(copy().includes('Höhe: unbekannt'));
assert(copy().includes('Tempo: unbekannt'));
assert.equal(list.children[1], button);
card.hidden = true;
const beforeHidden = copy();
now = 242000; timers.get(2000)(); timers.get(30000)();
assert.equal(copy(), beforeHidden);
assert.equal(fetches, 1);
console.log('PASS: preview metric text, routes, 2s prediction, stale freeze, missing data and hidden card');
