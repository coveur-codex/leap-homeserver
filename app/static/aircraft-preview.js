(() => {
  const script = document.currentScript;
  const card = document.querySelector('[data-preview-card="FLUGRADAR"]');
  if (!card) return;
  let snapshot = JSON.parse(card.querySelector('[data-aircraft-snapshot]').textContent);
  let received = performance.now(), selected = 0, pending = false;
  const list = card.querySelector('[data-aircraft-list]');
  const scope = card.querySelector('[data-aircraft-scope]');
  const status = card.querySelector('[data-aircraft-status]');
  const details = document.createElement('div');
  const next = document.createElement('button');
  next.type = 'button';
  next.onclick = () => { selected = (selected + 1) % snapshot.aircraft.length; render(); };
  list.replaceChildren(details, next);
  const rad = Math.PI / 180;
  function position(plane, age) {
    let lat = plane.latitude, lon = plane.longitude;
    const seconds = age + (plane.positionAgeSeconds || 0);
    const predicted = Number.isFinite(plane.groundSpeedKnots) && plane.groundSpeedKnots >= 0 &&
      Number.isFinite(plane.trackDegrees) && seconds >= 0;
    if (predicted) {
      const a = lat * rad, heading = plane.trackDegrees * rad;
      const d = plane.groundSpeedKnots * Math.min(seconds, 120) / 3600 / 3440.065;
      const b = Math.asin(Math.sin(a) * Math.cos(d) + Math.cos(a) * Math.sin(d) * Math.cos(heading));
      lon += Math.atan2(Math.sin(heading) * Math.sin(d) * Math.cos(a), Math.cos(d) - Math.sin(a) * Math.sin(b)) / rad;
      lon = (lon + 540) % 360 - 180;
      lat = b / rad;
    }
    return {lat, lon, predicted, old: seconds > 120};
  }
  function offset(point) {
    const center = snapshot.center;
    if (!center || ![center.latitude, center.longitude, point.lat, point.lon].every(Number.isFinite)) return null;
    const a = center.latitude * rad, b = point.lat * rad, delta = (point.lon - center.longitude) * rad;
    const h = Math.sin((b - a) / 2) ** 2 + Math.cos(a) * Math.cos(b) * Math.sin(delta / 2) ** 2;
    const km = 6371.0088 * 2 * Math.asin(Math.sqrt(Math.max(0, Math.min(1, h))));
    const bearing = Math.atan2(Math.sin(delta) * Math.cos(b), Math.cos(a) * Math.sin(b) - Math.sin(a) * Math.cos(b) * Math.cos(delta));
    return {km, bearing};
  }
  function line(tag, text) {
    const element = document.createElement(tag);
    element.textContent = text;
    details.append(element);
  }
  function render() {
    if (card.hidden) return;
    const planes = snapshot.aircraft || [];
    const age = (Number.isFinite(snapshot.ageSeconds) ? snapshot.ageSeconds :
      (Number.isFinite(Date.parse(snapshot.updated)) ? Math.max(0, (Date.now() - Date.parse(snapshot.updated)) / 1000) : 121)) + (performance.now() - received) / 1000;
    scope.replaceChildren();
    details.replaceChildren();
    next.hidden = !planes.length;
    if (!planes.length) { line('strong', 'Keine Flugdaten'); status.textContent = ''; return; }
    selected %= planes.length;
    const points = planes.map(plane => position(plane, age));
    const radius = (snapshot.radiusNm || 25) * 1.852;
    planes.forEach((plane, index) => {
      const point = offset(points[index]);
      if (!point || point.km > radius) return;
      const marker = document.createElement('b');
      marker.textContent = '✈';
      marker.style.left = `${50 + Math.sin(point.bearing) * point.km / radius * 46}%`;
      marker.style.top = `${50 - Math.cos(point.bearing) * point.km / radius * 46}%`;
      marker.style.transform = `translate(-50%, -50%) rotate(${(plane.trackDegrees || 0) - 90}deg)`;
      marker.style.color = index === selected ? '#ffe76b' : '#d8ffeb';
      scope.append(marker);
    });
    const plane = planes[selected], point = offset(points[selected]);
    line('strong', plane.callsign || plane.registration || plane.hex || 'Flugzeug');
    line('p', plane.typeName || 'Unbekannter Flugzeugtyp');
    const distance = point ? point.km : plane.distanceNm * 1.852;
    line('p', `Entfernung: ${distance.toFixed(1)} km`);
    line('p', `Höhe: ${Number.isFinite(plane.altitudeFeet) ? Math.round(plane.altitudeFeet * 0.3048) + ' m' : 'unbekannt'}`);
    line('p', `Tempo: ${Number.isFinite(plane.groundSpeedKnots) ? Math.round(plane.groundSpeedKnots * 1.852) + ' km/h' : 'unbekannt'}`);
    if (plane.originName) line('p', `Start: ${plane.originName}`);
    if (plane.destinationName) line('p', `Ziel: ${plane.destinationName}`);
    next.textContent = `Nächstes Flugzeug (${selected + 1}/${planes.length})`;
    status.textContent = `${Math.round(radius)} km · ${points[selected].old ? 'Alte Position' : points[selected].predicted ? 'Position geschätzt' : 'Gemeldete Position'}`;
  }
  async function refresh() {
    if (card.hidden || pending) return;
    pending = true;
    try {
      const response = await fetch(script.dataset.aircraftUrl);
      if (!response.ok) return;
      const data = await response.json();
      if (!Array.isArray(data.aircraft)) return;
      snapshot = data; received = performance.now(); render();
    } catch { /* Keep the previous observation and its age. */ }
    finally { pending = false; }
  }
  new MutationObserver(() => { if (!card.hidden) { render(); refresh(); } }).observe(card, {attributes: true, attributeFilter: ['hidden']});
  render(); refresh();
  setInterval(render, 2000);
  setInterval(refresh, 30000);
})();
