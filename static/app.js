const sessionId = 'session-' + Math.random().toString(36).substr(2, 9);
const appName = 'agent';

let currentDayIndex = 1;
let tripData = null;

// Day Metadata mapping dates/routes for visual fidelity
const dayRoutes = {
    1: { date: "2026-07-18", origin: "Santa Clara, CA", destination: "Driggs, ID", notes: "Arrival at Driggs Airbnb base. ~780 miles drive." },
    2: { date: "2026-07-19", origin: "Driggs, ID", destination: "Driggs, ID (Grand Teton)", notes: "Explore Grand Teton National Park. Jenny Lake base." },
    3: { date: "2026-07-20", origin: "Driggs, ID", destination: "West Yellowstone KOA", notes: "Travel to West Yellowstone. Transition day." },
    4: { date: "2026-07-21", origin: "West Yellowstone KOA", destination: "West Yellowstone (Yellowstone)", notes: "Explore Yellowstone NP (Old Faithful, Geyser basins)." },
    5: { date: "2026-07-22", origin: "West Yellowstone KOA", destination: "Gardiner, MT", notes: "Transition to Gardiner Airbnb near North Entrance." },
    6: { date: "2026-07-23", origin: "Gardiner, MT", destination: "West Glacier KOA / Kalispell", notes: "Travel to Glacier NP. Group splits lodging tonight." },
    7: { date: "2026-07-24", origin: "West Glacier KOA", destination: "West Glacier (Glacier NP)", notes: "Explore Glacier NP (Going-to-the-Sun Road)." },
    8: { date: "2026-07-25", origin: "West Glacier, MT", destination: "Santa Clara, CA", notes: "Overnight drive home via I-15 & I-80. ~1000 miles." }
};

// UI Elements
const chatMessages = document.getElementById('chat-messages');
const userInput = document.getElementById('user-input');
const sendBtn = document.getElementById('send-btn');
const socInput = document.getElementById('current-soc');
const timelineList = document.getElementById('timeline-list');
const uploadBtn = document.getElementById('upload-btn');
const uploadStatus = document.getElementById('upload-status');

// HUD Elements
const hudBatteryLevel = document.getElementById('hud-battery-level');
const hudBatteryPercent = document.getElementById('hud-battery-percent');
const hudRangeMiles = document.getElementById('hud-range-miles');
const hudDayOrigin = document.getElementById('hud-day-origin');
const hudDayDestination = document.getElementById('hud-day-destination');
const hudGroupStatus = document.getElementById('hud-group-status');
const hudAdvisories = document.getElementById('hud-advisories');

// Initialize App
document.addEventListener('DOMContentLoaded', async () => {
    await fetchTripContext();
    setupEventListeners();
    selectDay(1);
});

// Event Listeners
function setupEventListeners() {
    sendBtn.addEventListener('click', sendMessage);
    userInput.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') sendMessage();
    });
    
    // Update HUD battery gauge dynamically when typing SOC
    socInput.addEventListener('input', () => {
        let val = parseInt(socInput.value) || 80;
        val = Math.max(10, Math.min(100, val));
        updateBatteryHUD(val);
    });
    
    // Sync button sends direct prompt to agent to invoke save tool
    uploadBtn.addEventListener('click', () => {
        userInput.value = "Save and sync today's plan to Cloud Storage";
        sendMessage();
    });
}

// Fetch static context from backend
async function fetchTripContext() {
    try {
        const res = await fetch('/api/trip-context');
        tripData = await res.json();
        renderTimeline();
    } catch (e) {
        console.error("Failed to load trip context:", e);
    }
}

// Render the 8-day timeline dynamically
function renderTimeline() {
    timelineList.innerHTML = '';
    
    for (let day = 1; day <= 8; day++) {
        const item = dayRoutes[day];
        const timelineItem = document.createElement('div');
        timelineItem.className = `timeline-item ${day === currentDayIndex ? 'active' : ''}`;
        timelineItem.dataset.day = day;
        
        let lodgingText = "No Lodging";
        if (day === 8) {
            lodgingText = "Overnight Drive home";
        } else if (tripData && tripData.accommodations) {
            // Find accommodation corresponding to day's date
            const dateStr = item.date;
            const accom = tripData.accommodations.find(a => {
                const start = new Date(a.dates[0]);
                const end = new Date(a.dates[1]);
                const current = new Date(dateStr);
                return current >= start && current < end;
            });
            if (accom) {
                lodgingText = `${accom.type === 'airbnb' ? '🏡 Airbnb' : '⛺ Camp'} - ${accom.location || accom.name}`;
            }
        }
        
        timelineItem.innerHTML = `
            <div class="timeline-item-header">
                <span class="day-badge">Day ${day}</span>
                <span class="day-date">${item.date}</span>
            </div>
            <div class="day-lodging">
                <i class="fa-solid fa-map-location-dot"></i>
                <span>${lodgingText}</span>
            </div>
        `;
        
        timelineItem.addEventListener('click', () => selectDay(day));
        timelineList.appendChild(timelineItem);
    }
}

// Select a specific trip day
function selectDay(day) {
    currentDayIndex = day;
    
    // Update active class in list
    document.querySelectorAll('.timeline-item').forEach(item => {
        item.classList.toggle('active', parseInt(item.dataset.day) === day);
    });
    
    // Update HUD location details
    const route = dayRoutes[day];
    hudDayOrigin.textContent = route.origin;
    hudDayDestination.textContent = route.destination;
    
    // Update Group Split Badge
    // Group splits July 23, 24, 25 (Day 6, 7, 8)
    if (day >= 6 && day <= 8) {
        hudGroupStatus.className = "occupant-alert font-warning";
        hudGroupStatus.innerHTML = `
            <i class="fa-solid fa-users-slash"></i>
            <span>Group Split: West Glacier & Kalispell</span>
        `;
        document.getElementById('group-split-card').classList.add('text-accent');
    } else {
        hudGroupStatus.className = "occupant-alert";
        hudGroupStatus.innerHTML = `
            <i class="fa-solid fa-users"></i>
            <span>Group Together</span>
        `;
    }
    
    // Update mock advisories for the HUD based on where we are
    updateHUDAdvisories(day);
}

// Update HUD battery values
function updateBatteryHUD(soc) {
    hudBatteryLevel.style.width = `${soc}%`;
    hudBatteryPercent.textContent = `${soc}%`;
    
    // Model Y LR ranges: 3.57 miles per % (approx 260 total realistic range)
    const miles = Math.round(soc * 2.6);
    hudRangeMiles.textContent = miles;
}

// Mock advisories for selected park area
function updateHUDAdvisories(day) {
    hudAdvisories.innerHTML = '';
    
    let advisories = [];
    if (day === 2) { // Grand Teton area
        advisories = [
            { type: 'caution', title: 'Jenny Lake Ferry Delay', desc: 'Dock under maintenance. Long ferry queues.' }
        ];
    } else if (day === 3 || day === 4 || day === 5) { // Yellowstone area
        advisories = [
            { type: 'danger', title: 'Tower to Canyon Road Closed', desc: 'Mudslides have closed the road. Detour via Norris.' },
            { type: 'caution', title: 'North Rim Trail construction', desc: 'Expect closures near Lookout Point.' }
        ];
    } else if (day >= 6 && day <= 7) { // Glacier area
        advisories = [
            { type: 'danger', title: 'Highline Trail Closed', desc: 'Bear activity from Logan Pass to Granite Chalet.' },
            { type: 'caution', title: 'Many Glacier road entry permits', desc: 'Timed permits needed 6 AM - 3 PM.' }
        ];
    } else {
        advisories = [
            { type: 'info', title: 'No active road closures', desc: 'Routes appear clear. Drive safely!' }
        ];
    }
    
    advisories.forEach(adv => {
        const item = document.createElement('div');
        item.className = `advisory-item ${adv.type}`;
        
        let iconClass = 'fa-info-circle';
        if (adv.type === 'danger') iconClass = 'fa-circle-exclamation';
        if (adv.type === 'caution') iconClass = 'fa-triangle-exclamation';
        
        item.innerHTML = `
            <i class="fa-solid ${iconClass}"></i>
            <div>
                <h4>${adv.title}</h4>
                <p>${adv.desc}</p>
            </div>
        `;
        hudAdvisories.appendChild(item);
    });
}

// Send user message to SSE endpoint
async function sendMessage() {
    const text = userInput.value.trim();
    if (!text) return;
    
    const soc = parseInt(socInput.value) || 80;
    const route = dayRoutes[currentDayIndex];
    
    // Clear input
    userInput.value = '';
    
    // Add user message to chat
    appendMessage('user', text);
    
    // Create pre-grounded prompt to ensure agent knows the current state in UI
    const groundedPrompt = `
        [UI STATE: Trip Day ${currentDayIndex}, Date: ${route.date}, Current Origin: ${route.origin}, Tonight Destination: ${route.destination}, Current SOC: ${soc}%]
        User Query: ${text}
    `;
    
    // Add temporary thinking bubble
    const msgDiv = document.createElement('div');
    msgDiv.className = 'message agent';
    msgDiv.innerHTML = '<div class="message-content"><i class="fa-solid fa-spinner fa-spin"></i> Thinking...</div>';
    chatMessages.appendChild(msgDiv);
    chatMessages.scrollTop = chatMessages.scrollHeight;
    
    let currentMessageText = '';
    
    try {
        const response = await fetch('/run_sse', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                app_name: appName,
                user_id: 'family-1-user',
                session_id: sessionId,
                new_message: { parts: [{ text: groundedPrompt }] },
                streaming: true
            })
        });
        
        msgDiv.remove();
        
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        
        while (true) {
            const { value, done } = await reader.read();
            if (done) break;
            
            const chunk = decoder.decode(value, { stream: true });
            const lines = chunk.split('\n');
            
            for (const line of lines) {
                if (line.startsWith('data: ')) {
                    try {
                        const data = JSON.parse(line.substring(6));
                        processEvent(data);
                    } catch (e) {
                        console.error('Failed to parse JSON line:', line, e);
                    }
                }
            }
        }
        
        // Final message display
        if (currentMessageText) {
            appendMessage('agent', currentMessageText);
            
            // Check if response contains GCS signed URL and update HUD panel
            checkForGcsLink(currentMessageText);
        }
        
    } catch (error) {
        console.error('Error sending message:', error);
        msgDiv.innerHTML = '<div class="message-content">Error: Could not connect to trip planning agent.</div>';
    }
    
    function processEvent(event) {
        if (event.content && event.content.parts) {
            event.content.parts.forEach(part => {
                if (part.functionCall) {
                    const args = JSON.stringify(part.functionCall.args);
                    appendMessage('agent-thought', `🛠️ Tool Call: ${part.functionCall.name}(${args})`);
                    return;
                }
                
                if (part.functionResponse) {
                    const resp = part.functionResponse.response;
                    let resultText = '';
                    if (resp && resp.isError) {
                        resultText = `❌ Error: ${JSON.stringify(resp)}`;
                    } else if (resp) {
                        resultText = JSON.stringify(resp);
                    }
                    appendMessage('agent-thought', `📥 Tool Result: ${resultText}`);
                    return;
                }
                
                if (part.text) {
                    const hasToolCall = event.content.parts.some(p => p.functionCall);
                    if (hasToolCall) {
                        appendMessage('agent-thought', part.text);
                    } else {
                        currentMessageText += part.text;
                    }
                }
            });
        }
    }
}

// Check if message has sync complete and show in GCS widget
function checkForGcsLink(text) {
    // Regex for GCS share link: [Sync Complete! View shareable cloud itinerary here](url)
    // Or check for general markdown link
    const regex = /\[(?:Sync Complete! View shareable cloud itinerary here|View shareable cloud itinerary here)\]\((https:\/\/storage\.googleapis\.com\/[^\)]+)\)/i;
    const match = text.match(regex);
    
    if (match && match[1]) {
        const url = match[1];
        uploadStatus.innerHTML = `
            <div class="sync-success">
                <div class="sync-msg">
                    <i class="fa-solid fa-circle-check"></i>
                    <span>Plan Uploaded to GCS!</span>
                </div>
                <a href="${url}" target="_blank" class="sync-link">
                    <i class="fa-solid fa-up-right-from-square"></i> Day ${currentDayIndex} Plan Link
                </a>
            </div>
        `;
    }
}

function appendMessage(role, text) {
    const msgDiv = document.createElement('div');
    msgDiv.className = `message ${role}`;
    msgDiv.innerHTML = `<div class="message-content">${processText(text)}</div>`;
    chatMessages.appendChild(msgDiv);
    chatMessages.scrollTop = chatMessages.scrollHeight;
}

function processText(text) {
    if (!text) return '';
    return marked.parse(text);
}
