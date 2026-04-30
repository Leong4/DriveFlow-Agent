// DriveFlow Agent Frontend App
console.log("APP_JS_VERSION_STEP1");
let map;
let directionsService;
let directionsRenderer;
let markers = [];

// Stores the parsed_tasks from the most recent successful run.
// Sent as existing_tasks when the next query looks like an itinerary edit.
let latestParsedTasks = null;

// Stores the last pre-route candidate state so selectCandidate() can reference it.
// Shape: { parsedTasks, query, origin, battery, range } | null
let latestCandidateContext = null;

// Stores the pending_clarification context from the last clarification_needed response.
// Forwarded as pending_clarification in the next request so the follow-up interpreter runs.
let latestClarificationContext = null;

/**
 * Return true when the query looks like a continuation / append turn:
 *   "and take me to ...", "then go to ...", "also stop at ...",
 *   "再去 ...", "然后去 ...", "顺路 ..."
 *
 * These should be merged into the existing itinerary rather than parsed fresh.
 * Only triggered when latestParsedTasks is non-null (prior context exists).
 */
function isContinuationQuery(query) {
    const q = query.trim();
    return (
        /^and\s+(then\s+)?(take|go|drive|navigate|head|stop|find)/i.test(q) ||
        /^then\s+(take|go|drive|navigate|head|stop|also|find)/i.test(q) ||
        /^also\s+(take|go|drive|stop|find)/i.test(q) ||
        /\b(?:on|along)\s+the\s+way\b/i.test(q) ||
        /^路上/u.test(q) ||
        /^再(?:去|到|找)/u.test(q) ||
        /^然后(?:去|到)/u.test(q) ||
        /^顺路/u.test(q)
    );
}

/**
 * Return true when the query string matches one of the edit-intent patterns
 * that itinerary_editor.py handles: insert_before, replace, remove.
 * This keeps the heuristic consistent with the backend pattern set.
 */
function isEditQuery(query) {
    const q = query.toLowerCase().trim();
    return (
        /^before\s+/.test(q)           ||  // "Before B, stop by D."
        /replace\s+.+\s+with\s+/.test(q) || // "Replace B with D."
        /don'?t\s+go\s+to\s+/.test(q)  ||  // "Don't go to B, replace it with D." / "...anymore"
        /i(?:'m|\s+am)\s+(?:not|no\s+longer)\s+going\s+to\s+/.test(q) || // "I'm not going to B anymore."
        /i\s+don'?t\s+need\s+.+?(?:\s+anymore)?$/.test(q) || // "I don't need B anymore."
        /don'?t\s+stop\s+at\s+/.test(q) || // "Don't stop at B."
        /\bremove\s+/.test(q)           ||  // "Remove B."
        /\bskip\s+/.test(q)             ||  // "Skip B."
        /\bcancel\s+/.test(q)           ||  // "Cancel B."
        /\bdrop\s+/.test(q)             ||  // "Drop B." / "We can drop B."
        /\b(?:insert|add)\s+.+?\s+before\s+/.test(q) || // "Insert Boots before the airport."
        /在\s*.+?\s*前面\s*.*(?:去|到|加|插入)/.test(q) || // "在 B 前面先去 D"
        /先\s*(?:去|到).+?[，,]\s*再\s*(?:去|到)/.test(q) || // "先去 D，再去 B"
        /不\s*去\s*.+?\s*了/.test(q)    ||  // "不去 B 了" / "不去 B 了，换成 D"
        /把\s*.+?\s*(?:换成|换为|改成)/.test(q) // "把 B 换成 D"
    );
}

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

    // Edit flow: natural-language edit instructions (insert/replace/remove).
    if (latestParsedTasks && isEditQuery(query)) {
        payload.existing_tasks = latestParsedTasks;
        console.log("[Edit mode] Sending existing_tasks:", latestParsedTasks.length, "tasks");
    }
    // Continuation flow: "and then ...", "再去 ..." — append to existing itinerary.
    else if (latestParsedTasks && isContinuationQuery(query)) {
        payload.existing_tasks = latestParsedTasks;
        payload.is_continuation = true;
        console.log("[Continuation mode] Merging into existing_tasks:", latestParsedTasks.length, "tasks");
    }

    // Forward pending clarification context so the follow-up interpreter can run.
    if (latestClarificationContext) {
        payload.pending_clarification = latestClarificationContext;
        console.log("[Clarification follow-up] Forwarding pending_clarification:", latestClarificationContext.domain);
    }

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
            // Only update the task chain for fully resolved routes (not blocking states).
            // Blocking states (clarification_needed / candidate_selection_needed) return
            // only the tasks relevant to that sub-query, which would erase prior context
            // (e.g. the destination anchor) that is still needed for re-entry.
            if (data.parsed_tasks && (!data.pre_route_status || data.pre_route_status === 'ready_for_routing')) {
                latestParsedTasks = data.parsed_tasks;
                console.log("[Task chain updated] latestParsedTasks:", latestParsedTasks.length, "tasks");
            }
            // Save context for candidate selection so selectCandidate() can re-submit.
            if (data.pre_route_candidates && data.pre_route_candidates.length > 0) {
                latestCandidateContext = {
                    parsedTasks: data.parsed_tasks,
                    origin:      origin || 'University of Nottingham',
                    battery:     batStr ? parseInt(batStr) : null,
                    range:       rngStr ? parseInt(rngStr) : null,
                };
            } else {
                latestCandidateContext = null;
            }
            // Store or clear the pending clarification context.
            if (data.pending_clarification) {
                latestClarificationContext = data.pending_clarification;
                console.log("[Clarification] Stored pending_clarification, domain:", latestClarificationContext.domain);
            } else {
                latestClarificationContext = null;
            }
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

    // ── Step 1: Candidate selection panel ────────────────────────────────────
    if (data.pre_route_candidates && data.pre_route_candidates.length > 0) {
        renderCandidates(data.pre_route_candidates, data.pre_route_status);
    } else {
        hideCandidates();
    }

    document.getElementById('preParsed').innerText = JSON.stringify(data.parsed_tasks, null, 2);
    document.getElementById('preGraph').innerText = data.graph_text || '-';
    document.getElementById('preState').innerText = JSON.stringify(data.state, null, 2);
    document.getElementById('preTool').innerText = JSON.stringify(data.tool_result, null, 2);
}

// ── Candidate selection helpers ───────────────────────────────────────────────

function renderCandidates(candidates, preRouteStatus) {
    const box    = document.getElementById('boxCandidates');
    const header = document.getElementById('lblCandidatesHeader');
    const list   = document.getElementById('candidateList');

    header.innerText = preRouteStatus === 'candidate_selection_needed'
        ? 'Select a location:'
        : 'Nearby options:';

    list.innerHTML = '';
    candidates.forEach((c) => {
        const btn = document.createElement('button');
        btn.className = 'candidate-btn';
        btn.innerHTML =
            `<span class="cand-name">${escapeHtml(c.name)}</span>` +
            `<span class="cand-address">${escapeHtml(c.address || '')}</span>` +
            `<span class="reason-tag">${escapeHtml(c.reason_tag || '')}</span>`;
        btn.addEventListener('click', () => selectCandidate(c));
        list.appendChild(btn);
    });

    box.classList.remove('hidden');
}

function hideCandidates() {
    document.getElementById('boxCandidates').classList.add('hidden');
    document.getElementById('candidateList').innerHTML = '';
    latestCandidateContext = null;
}

/**
 * Called when the user clicks a candidate button.
 * Sends a candidate-resolution request to the backend: the backend replaces
 * the matching vague/brand task with the selected POI and builds the route.
 */
async function selectCandidate(candidate) {
    if (!latestCandidateContext) return;

    const { parsedTasks, origin, battery, range } = latestCandidateContext;

    // WS3: Restore destination anchor if the candidate context's task list does not
    // include a destination (e.g. follow-up clarification flow only produced a stop).
    // Pull the destination from the last known full route so it is not silently lost.
    let taskList = parsedTasks;
    const hasDestination = parsedTasks.some(t => t.type === 'destination');
    if (!hasDestination && latestParsedTasks) {
        const priorDest = latestParsedTasks.find(t => t.type === 'destination');
        if (priorDest) {
            taskList = [...parsedTasks, priorDest];
            console.log("[Re-entry] Injecting prior destination anchor:", priorDest.name);
        }
    }

    const payload = {
        query:              document.getElementById('queryInput').value,
        origin:             origin || 'University of Nottingham',
        existing_tasks:     taskList,
        selected_candidate: candidate,
    };
    if (battery) payload.battery_level = battery;
    if (range)   payload.remaining_range_km = range;

    setLoading(true);
    try {
        const resp = await fetch('/demo/run', {
            method:  'POST',
            headers: { 'Content-Type': 'application/json' },
            body:    JSON.stringify(payload),
        });
        const contentType = resp.headers.get('content-type');
        const data = contentType && contentType.includes('application/json')
            ? await resp.json()
            : { detail: await resp.text() };

        if (resp.ok) {
            if (data.parsed_tasks) latestParsedTasks = data.parsed_tasks;
            latestClarificationContext = null; // candidate resolution ends any pending clarification
            updateUIState(data);
            updateMap(data.map_data);
        } else {
            const msg = data.detail
                ? (typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail))
                : 'Request failed';
            const errorBanner = document.getElementById('errorBanner');
            errorBanner.innerText = 'Error: ' + msg;
            errorBanner.classList.remove('hidden');
        }
    } catch (err) {
        console.error('selectCandidate fetch error:', err);
    } finally {
        setLoading(false);
    }
}

function escapeHtml(str) {
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
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
    const hasDestination = !!(
        mapData.destination &&
        mapData.destination.present !== false &&
        (mapData.destination.lat != null || mapData.destination.lng != null || mapData.destination.label)
    );

    // Google Directions requires a destination. For stop-only itineraries,
    // route to the last stop for display without changing the backend task chain.
    const routeStops = hasDestination ? stops : stops.slice(0, -1);
    const finalStop = hasDestination ? null : stops[stops.length - 1];
    const waypoints = routeStops.map(stop => ({
        location: (stop.lat != null && stop.lng != null) ? { lat: stop.lat, lng: stop.lng } : stop.label,
        stopover: true
    }));

    // Build Destination
    let destination;
    if (hasDestination && mapData.destination.lat != null && mapData.destination.lng != null) {
        destination = { lat: mapData.destination.lat, lng: mapData.destination.lng };
    } else if (hasDestination) {
        destination = mapData.destination.label;
    } else if (finalStop) {
        destination = (finalStop.lat != null && finalStop.lng != null)
            ? { lat: finalStop.lat, lng: finalStop.lng }
            : finalStop.label;
    } else {
        if (mapData.origin.lat != null) addMarker({lat: mapData.origin.lat, lng: mapData.origin.lng}, mapData.origin.label, "O", "#0d6efd");
        return;
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
            for (let i = 0; i < routeStops.length; i++) {
                let color = routeStops[i].type === 'charging_station' ? "#198754" : "#fd7e14";
                let label = routeStops[i].type === 'charging_station' ? "C" : "S";
                addMarker(legs[i].end_location, routeStops[i].label, label, color);
            }

            if (hasDestination) {
                // Destination marker
                addMarker(legs[legs.length - 1].end_location, mapData.destination.label, "D", "#dc3545"); // Red
            } else if (finalStop) {
                let color = finalStop.type === 'charging_station' ? "#198754" : "#fd7e14";
                let label = finalStop.type === 'charging_station' ? "C" : "S";
                addMarker(legs[legs.length - 1].end_location, finalStop.label, label, color);
            }

        } else {
            console.error("Directions request failed due to " + status);
            // Fallback: Just draw markers if routing fails
            if (mapData.origin.lat != null) addMarker({lat: mapData.origin.lat, lng: mapData.origin.lng}, mapData.origin.label, "O", "#0d6efd");
            stops.forEach(s => {
                if (s.lat != null) addMarker({lat: s.lat, lng: s.lng}, s.label, "S", "#fd7e14");
            });
            if (hasDestination && mapData.destination.lat != null) addMarker({lat: mapData.destination.lat, lng: mapData.destination.lng}, mapData.destination.label, "D", "#dc3545");
        }
    });
}

// Start
document.addEventListener("DOMContentLoaded", init);
