import { useEffect, useRef } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";

const ACCRA_CENTER = [5.6037, -0.1870]; // database/seed_generator.py's synthetic jitter center

function toneFor(prob, blockThreshold, alertThreshold) {
  if (prob >= blockThreshold) return "#d03b3b";
  if (prob >= alertThreshold) return "#fab219";
  return "#0ca30c";
}

/**
 * A real map, not a placeholder: plain Leaflet (no react-leaflet wrapper -
 * consistent with this app's no-extra-framework approach elsewhere) over
 * OpenStreetMap tiles, plotting each flagged subscriber's CURRENT position
 * (colored by fraud probability) with a dashed line back to their HOME
 * position - the same current-vs-home delta the Geo-Location Deltas table
 * shows, drawn geographically instead of as coordinates in a row. The
 * underlying coordinates are synthetic (see api/geocode.py's module
 * docstring), so this is explicitly labeled illustrative, not real
 * surveillance data.
 */
export function FraudMap({ rows, blockThreshold, alertThreshold, onSelect }) {
  const containerRef = useRef(null);
  const mapRef = useRef(null);
  const layerRef = useRef(null);

  useEffect(() => {
    const map = L.map(containerRef.current, { scrollWheelZoom: true }).setView(ACCRA_CENTER, 11);
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
      maxZoom: 18,
    }).addTo(map);
    mapRef.current = map;
    layerRef.current = L.layerGroup().addTo(map);
    return () => map.remove();
  }, []);

  useEffect(() => {
    const layer = layerRef.current;
    if (!layer || !rows) return;
    layer.clearLayers();

    const points = [];
    for (const r of rows) {
      if (r.current_latitude == null || r.avg_latitude == null) continue;
      const current = [r.current_latitude, r.current_longitude];
      const home = [r.avg_latitude, r.avg_longitude];
      points.push(current, home);
      const color = toneFor(r.max_fraud_probability, blockThreshold, alertThreshold);

      L.polyline([home, current], { color, weight: 1.5, dashArray: "4 4", opacity: 0.6 }).addTo(layer);
      L.circleMarker(home, { radius: 4, color, weight: 1, fillColor: color, fillOpacity: 0.15 }).addTo(layer);

      const marker = L.circleMarker(current, {
        radius: 7,
        color,
        weight: 2,
        fillColor: color,
        fillOpacity: 0.75,
      }).addTo(layer);

      const pct = Math.round(r.max_fraud_probability * 100);
      const html = `
        <div class="map-popup">
          <strong>${r.full_name}</strong> <span class="muted">(${r.user_id})</span>
          <div>Fraud probability: <strong>${pct}%</strong></div>
          <div class="muted">Current: ${r.current_address?.formatted ?? "—"}</div>
          <div class="muted">Home: ${r.home_address?.formatted ?? "—"}</div>
          <div class="muted">${r.distance_from_home_km ?? "—"} km from home</div>
          <button type="button" class="map-popup-btn" data-txn-id="${r.top_txn_id}">View Transaction</button>
        </div>
      `;
      marker.bindPopup(html);
      marker.on("popupopen", (e) => {
        const btn = e.popup.getElement().querySelector(".map-popup-btn");
        btn?.addEventListener("click", () => {
          e.popup.close();
          onSelect?.(r.top_txn_id);
        });
      });
    }

    // Subscribers now span all of Ghana's regions, not just Accra, so a
    // fixed Accra-only view would silently hide markers outside it - fit
    // to whatever's actually plotted instead, falling back to the old
    // Accra view when there's nothing to show yet.
    if (points.length > 0) {
      mapRef.current.fitBounds(L.latLngBounds(points), { padding: [40, 40], maxZoom: 12 });
    } else {
      mapRef.current.setView(ACCRA_CENTER, 11);
    }
  }, [rows, blockThreshold, alertThreshold, onSelect]);

  return (
    <div className="map-wrap">
      <div ref={containerRef} className="map-canvas" />
      <div className="map-legend">
        <div><span className="map-legend-dot" style={{ background: "#d03b3b" }} /> Blocked-level</div>
        <div><span className="map-legend-dot" style={{ background: "#fab219" }} /> Flagged</div>
        <div><span className="map-legend-dot" style={{ background: "#0ca30c" }} /> Below threshold</div>
      </div>
    </div>
  );
}
