// DriveFlow Agent Frontend App
console.log("APP_JS_VERSION_FIX_2");
let map;
let directionsService;
let directionsRenderer;
let markers = [];

// ── Initialization ──

async function init() {
    // 1. Fetch Maps API Key
    try {
        const resp = await fetch('/demo/config');
        const data = await resp.json();
        if (data.google_maps_api_key) {
            loadGoogleMaps(data.google_maps_api_key);
        } else {
            alert("No Google Maps API key found in backend config.");
        }
    } catch (err) {
        console.error("Failed to load generic config", err);
    }

    // 2. Bind UI events
    document.getElementById('runBtn').addEventListener('click', runAgent);
}

function loadGoogleMaps(apiKey) {
    const script = document.createElement('script');
    script.src = `https://maps.googleapis.com/maps/api/js?key=${apiKey}&callback=initMap`;
    script.async = true;
    script.defer = true;
    document.head.appendChild(script);
}

window.initMap = function() {
    // Default origin: University of Nottingham
    const defaultLocation = { lat: 52.938, lng: -1.198 };
    
    map = new google.maps.Map(document.getElementById("map"), {
        center: defaultLocation,
        zoom: 12,
        mapTypeControl: false,
    });

    directionsService = new google.maps.DirectionsService();
    directionsRenderer = new google.maps.DirectionsRenderer({
        map: map,
        suppressMarkers: true // We will draw our own markers
    });
};

function applyPreset(query, battery, range) {
    document.getElementById('queryInput').value = query;
    document.getElementById('batteryInput').value = battery !== null ? battery : '';
    document.getElementById('rangeInput').value = range !== null ? range : '';
}

// ── Main Execution ──

async function runAgent() {
    const errorBanner = document.getElementById('errorBanner');
    errorBanner.classList.add('hidden');
    errorBanner.innerText = '';
    
    const query = document.getElementById('queryInput').value;
    const origin = document.getElementById('originInput').value;
    const batStr = document.getElementById('batteryInput').value;
    const rngStr = document.getElementById('rangeInput').value;

    if (!query) {
        errorBanner.innerText = "Please enter a query.";
        errorBanner.classList.remove('hidden');
        return;
    }

    const payload = {
        query: query,
        origin: origin || "University of Nottingham",
    };

    if (batStr) payload.battery_level = parseInt(batStr);
    if (rngStr) payload.remaining_range_km = parseInt(rngStr);

    setLoading(true);

    try {
        const resp = await fetch('/demo/run', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });

        let data;
        const contentType = resp.headers.get("content-type");
        if (contentType && contentType.includes("application/json")) {
            data = await resp.json();
        } else {
            data = { detail: await resp.text() };
        }
        
        if (resp.ok) {
            updateUIState(data);
            updateMap(data.map_data);
            
            // If the Backend returns a failure status but HTTP 200, show it
            if (data.state && data.state.status === 'failed') {
                errorBanner.innerText = data.guardrail_message || "Agent execution failed.";
                errorBanner.classList.remove('hidden');
            }
        } else {
            const errorMsg = data.detail ? (typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail)) : "Request failed";
            errorBanner.innerText = "Error: " + errorMsg;
            errorBanner.classList.remove('hidden');
            console.error("Backend Error Response:", data);
        }
    } catch (err) {
        console.error("Fetch Exception:", err);
        errorBanner.innerText = "Failed to connect to backend: " + err.message;
        errorBanner.classList.remove('hidden');
    } finally {
        setLoading(false);
    }
}

// ── UI Updates ──

function setLoading(isLoading) {
    const loader = document.getElementById('loader');
    const btn = document.getElementById('runBtn');
    if (isLoading) {
        loader.classList.remove('hidden');
        btn.disabled = true;
    } else {
        loader.classList.add('hidden');
        btn.disabled = false;
    }
}

function updateUIState(data) {
    document.getElementById('lblStatus').innerText = data.state.status || 'unknown';
    
    const boxClarif = document.getElementById('boxClarification');
    const lblClarif = document.getElementById('lblClarification');
    if (data.clarification_text) {
        lblClarif.innerText = data.clarification_text;
        boxClarif.classList.remove('hidden');
    } else {
        boxClarif.classList.add('hidden');
    }

    const boxGuard = document.getElementById('boxGuardrail');
    const lblGuard = document.getElementById('lblGuardrail');
    if (data.guardrail_message) {
        lblGuard.innerText = data.guardrail_message;
        boxGuard.classList.remove('hidden');
    } else {
        boxGuard.classList.add('hidden');
    }

    document.getElementById('preParsed').innerText = JSON.stringify(data.parsed_tasks, null, 2);
    document.getElementById('preGraph').innerText = data.graph_text || '-';
    document.getElementById('preState').innerText = JSON.stringify(data.state, null, 2);
    document.getElementById('preTool').innerText = JSON.stringify(data.tool_result, null, 2);
}

// ── Map Updates ──

function clearMap() {
    markers.forEach(m => m.setMap(null));
    markers = [];
    if (directionsRenderer) directionsRenderer.set('directions', null);
}

function addMarker(position, title, labelStr, color) {
    const marker = new google.maps.Marker({
        position: position,
        map: map,
        title: title,
        label: {
            text: labelStr,
            color: 'white',
            fontWeight: 'bold'
        },
        icon: {
            path: google.maps.SymbolPath.BACKWARD_CLOSED_ARROW,
            fillColor: color,
            fillOpacity: 1,
            strokeWeight: 1,
            strokeColor: '#FFFFFF',
            scale: 6
        }
    });
    markers.push(marker);
}

function updateMap(mapData) {
    clearMap();
    if (!map || !mapData) return;

    if (!mapData.origin) return;

    console.log("[Map Debug] origin:", mapData.origin);
    console.log("[Map Debug] stops:", mapData.stops);
    console.log("[Map Debug] destination:", mapData.destination);

    // Build Origin
    let origin;
    if (mapData.origin.lat != null && mapData.origin.lng != null) {
        origin = { lat: mapData.origin.lat, lng: mapData.origin.lng };
    } else {
        origin = mapData.origin.label; // Fallback to string
    }

    // Build Stops
    const stops = mapData.stops || [];
    const waypoints = stops.map(stop => ({
        location: (stop.lat != null && stop.lng != null) ? { lat: stop.lat, lng: stop.lng } : stop.label,
        stopover: true
    }));

    // Build Destination
    let destination;
    if (mapData.destination.lat != null && mapData.destination.lng != null) {
        destination = { lat: mapData.destination.lat, lng: mapData.destination.lng };
    } else {
        destination = mapData.destination.label;
    }

    // Request directions so Google computes the polyline and geocodes any text elements
    const request = {
        origin: origin,
        destination: destination,
        waypoints: waypoints,
        travelMode: google.maps.TravelMode.DRIVING
    };

    directionsService.route(request, (result, status) => {
        if (status === google.maps.DirectionsStatus.OK) {
            directionsRenderer.setDirections(result);
            
            // Draw custom markers based on the result legs to get exact geocoded origin/dest
            const route = result.routes[0];
            const legs = route.legs;
            
            // Origin marker
            addMarker(legs[0].start_location, mapData.origin.label, "O", "#0d6efd"); // Blue
            
            // Waypoint markers
            for (let i = 0; i < stops.length; i++) {
                let color = stops[i].type === 'charging_station' ? "#198754" : "#fd7e14";
                let label = stops[i].type === 'charging_station' ? "C" : "S";
                addMarker(legs[i].end_location, stops[i].label, label, color);
            }

            // Destination marker
            addMarker(legs[legs.length - 1].end_location, mapData.destination.label, "D", "#dc3545"); // Red

        } else {
            console.error("Directions request failed due to " + status);
            // Fallback: Just draw markers if routing fails
            if (mapData.origin.lat != null) addMarker({lat: mapData.origin.lat, lng: mapData.origin.lng}, mapData.origin.label, "O", "#0d6efd");
            stops.forEach(s => {
                if (s.lat != null) addMarker({lat: s.lat, lng: s.lng}, s.label, "S", "#fd7e14");
            });
            if (mapData.destination.lat != null) addMarker({lat: mapData.destination.lat, lng: mapData.destination.lng}, mapData.destination.label, "D", "#dc3545");
        }
    });
}

// Start
document.addEventListener("DOMContentLoaded", init);
