import os
import re
import yaml
import json
import time
import datetime
import urllib.request
from google.cloud import storage
from google.adk.tools.mcp_tool.mcp_toolset import MCPToolset
from google.adk.tools.mcp_tool.mcp_session_manager import StreamableHTTPConnectionParams

MAPS_MCP_URL = "https://mapstools.googleapis.com/mcp"

def get_maps_mcp_toolset():
    """
    Exposes Google Maps MCP tools (search_places, compute_routes, lookup_weather) to the LLM agent.
    """
    # Load env manually in case it hasn't been loaded yet
    from dotenv import load_dotenv
    load_dotenv()
    maps_api_key = os.getenv('MAPS_API_KEY', 'no_api_found')
    
    tools = MCPToolset(
        connection_params=StreamableHTTPConnectionParams(
            url=MAPS_MCP_URL,
            headers={
                "X-Goog-Api-Key": maps_api_key
            },
            timeout=30.0,
            sse_read_timeout=300.0
        )
    )
    print("Maps MCP Toolset configured.")
    return tools

def get_trip_context() -> dict:
    """
    Parses the static trip context from specs/01-trip-context.md.
    Uses the YAML block inside the spec file as the single source of truth.
    """
    try:
        current_dir = os.path.dirname(os.path.abspath(__file__))
        spec_path = os.path.join(current_dir, "specs", "01-trip-context.md")
        
        if not os.path.exists(spec_path):
            return {"error": "Trip context spec not found at " + spec_path}
            
        with open(spec_path, "r", encoding="utf-8") as f:
            content = f.read()
            
        # Extract YAML code block
        match = re.search(r"```yaml\n(.*?)\n```", content, re.DOTALL)
        if match:
            yaml_content = match.group(1)
            data = yaml.safe_load(yaml_content)
            return data
        else:
            return {"error": "No YAML block found in 01-trip-context.md"}
    except Exception as e:
        return {"error": f"Failed to parse trip context: {str(e)}"}

def calculate_tesla_segments(distance_miles: float, current_soc: int) -> dict:
    """
    Calculates Tesla Model Y Long Range battery consumption for a drive segment.
    
    Args:
        distance_miles: The distance of the drive segment in miles.
        current_soc: The current battery state of charge (SOC) percentage (10 to 100).
        
    Returns:
        A dictionary with reachability, energy needed, projected arrival SOC, and recommendations.
    """
    # Usable battery capacity: 75 kWh
    # Average consumption: 280 Wh/mile (0.28 kWh/mile)
    # Safety buffer: 10% SOC
    battery_capacity_kwh = 75.0
    consumption_rate_kwh_per_mile = 0.280
    safety_buffer_soc = 10
    
    # Calculate energy required
    energy_needed_kwh = distance_miles * consumption_rate_kwh_per_mile
    soc_needed = (energy_needed_kwh / battery_capacity_kwh) * 100.0
    
    projected_arrival_soc = current_soc - soc_needed
    reachable = projected_arrival_soc >= safety_buffer_soc
    
    max_range_at_current_soc = ((current_soc - safety_buffer_soc) / 100.0) * (battery_capacity_kwh / consumption_rate_kwh_per_mile)
    
    result = {
        "segment_distance_miles": round(distance_miles, 1),
        "starting_soc": current_soc,
        "energy_needed_kwh": round(energy_needed_kwh, 2),
        "soc_needed_percent": round(soc_needed, 1),
        "projected_arrival_soc": round(projected_arrival_soc, 1),
        "reachable": reachable,
        "max_range_before_charge": round(max_range_at_current_soc, 1),
        "safety_buffer_soc": safety_buffer_soc
    }
    
    if reachable:
        result["recommendation"] = "Reachable directly. No charging stop required for this segment."
    else:
        result["recommendation"] = f"Warning: Target location is out of range. You need to charge. Your maximum range is {round(max_range_at_current_soc, 1)} miles. Suggest searching for a 'Tesla Supercharger' along the route before this limit."
        
    return result

def get_nps_alerts(park_name: str) -> list:
    """
    Retrieves active alerts and road/trail closures for the given National Park.
    Uses the NPS API if NPS_API_KEY is defined in environment, otherwise falls back to mock alerts.
    
    Args:
        park_name: Name of the park ('Yellowstone', 'Grand Teton', or 'Glacier').
    """
    from dotenv import load_dotenv
    load_dotenv()
    
    park_mappings = {
        "yellowstone": "yell",
        "grand teton": "grte",
        "glacier": "glac"
    }
    
    name_lower = park_name.lower().strip()
    park_code = None
    for k, v in park_mappings.items():
        if k in name_lower:
            park_code = v
            break
            
    if not park_code:
        return [{"title": "Unknown Park", "description": f"No alert mapping for park name: '{park_name}'"}]
        
    nps_api_key = os.getenv("NPS_API_KEY")
    
    # Mock Alerts dataset
    mock_alerts = {
        "yell": [
            {
                "title": "Tower-Roosevelt to Canyon Road Mudslide Closure",
                "description": "The road between Tower Junction and Canyon Village is closed due to recent mudslides. Detours are in place via Norris Junction.",
                "category": "Danger"
            },
            {
                "title": "Grand Canyon of the Yellowstone North Rim Trail Restriction",
                "description": "Portions of the North Rim Trail are closed for boardwalk restoration. Expect minor delays and trail rerouting near Lookout Point.",
                "category": "Caution"
            }
        ],
        "grte": [
            {
                "title": "Signal Mountain Summit Road Repairs",
                "description": "Signal Mountain Road is closed daily from 8 AM to 4 PM for asphalt repairs. Scenic overlooks are inaccessible during these hours.",
                "category": "Information"
            },
            {
                "title": "Jenny Lake Ferry Construction Delay",
                "description": "The west shore boat dock is undergoing maintenance. Ferry services are operational but expect longer boarding queues.",
                "category": "Caution"
            }
        ],
        "glac": [
            {
                "title": "Highline Trail Temporary Grizzly Closure",
                "description": "Highline Trail is temporarily closed from Logan Pass to Granite Park Chalet due to an active grizzly bear carcass encounter.",
                "category": "Danger"
            },
            {
                "title": "Many Glacier Road Timed Entry Permits",
                "description": "Timed entry reservation is required to enter the Many Glacier valley between 6 AM and 3 PM. Plan accordingly.",
                "category": "Caution"
            }
        ]
    }
    
    if not nps_api_key or nps_api_key == "YOUR_NPS_API_KEY" or nps_api_key.strip() == "":
        print(f"Using mock alerts for park code: {park_code}")
        return mock_alerts.get(park_code, [])
        
    try:
        url = f"https://developer.nps.gov/api/v1/alerts?parkCode={park_code}"
        req = urllib.request.Request(
            url,
            headers={"X-Api-Key": nps_api_key}
        )
        with urllib.request.urlopen(req, timeout=10) as response:
            res_data = json.loads(response.read().decode())
            raw_alerts = res_data.get("data", [])
            
            parsed_alerts = []
            for alert in raw_alerts:
                parsed_alerts.append({
                    "title": alert.get("title"),
                    "description": alert.get("description"),
                    "category": alert.get("category", "Warning")
                })
            return parsed_alerts
    except Exception as e:
        print(f"Error fetching NPS alerts: {e}. Falling back to mock alerts.")
        return mock_alerts.get(park_code, [])

def save_and_upload_trip_plan(day_index: int, day_title: str, plan_markdown: str) -> str:
    """
    Saves the daily trip itinerary locally and uploads it to Google Cloud Storage.
    Generates a 24-hour signed URL for the uploaded file.
    
    Args:
        day_index: Index of the trip day (e.g. 1 for Day 1).
        day_title: Title description of the day (e.g. 'Santa Clara to Elko').
        plan_markdown: Formatted markdown content of the day's itinerary.
    """
    from dotenv import load_dotenv
    load_dotenv()
    project_id = os.getenv('GOOGLE_CLOUD_PROJECT', 'project_not_set')
    bucket_name = f"yellowstone-trip-data-{project_id}"
    
    # Save locally to temp/tmp directory first
    current_dir = os.path.dirname(os.path.abspath(__file__))
    tmp_dir = os.path.join(current_dir, "tmp")
    os.makedirs(tmp_dir, exist_ok=True)
    
    filename = f"day_{day_index}_plan.md"
    local_path = os.path.join(tmp_dir, filename)
    
    header = f"# Trip Itinerary: Day {day_index} - {day_title}\n"
    header += f"*Generated on {datetime.date.today().isoformat()}*\n\n"
    
    full_content = header + plan_markdown
    
    with open(local_path, "w", encoding="utf-8") as f:
        f.write(full_content)
        
    try:
        storage_client = storage.Client()
        bucket = storage_client.bucket(bucket_name)
        
        # Check if bucket exists, create if not
        if not bucket.exists():
            bucket = storage_client.create_bucket(bucket_name, location="us-west1")
            
        blob = bucket.blob(filename)
        blob.upload_from_filename(local_path)
        
        # Generate a signed URL valid for 24 hours
        url = blob.generate_signed_url(
            version="v4",
            expiration=datetime.timedelta(hours=24),
            method="GET",
        )
        return url
    except Exception as e:
        print(f"Error uploading plan to GCS: {e}")
        # Return local path prefix if GCS upload fails (so frontend resolves it)
        return f"/tmp/{filename}"
