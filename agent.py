import os
import dotenv
import tools
from google.adk.agents import LlmAgent
from google.adk.tools import AgentTool

dotenv.load_dotenv()

PROJECT_ID = os.getenv('GOOGLE_CLOUD_PROJECT', 'project_not_set')

# Get the Maps MCP toolset
maps_toolset = tools.get_maps_mcp_toolset()

# --- Charging Planner Sub-agent (AgentTool Mode) ---

charging_planner = LlmAgent(
    model='gemini-2.5-pro',
    name='charging_planner',
    description="Plans charging stops and segments for EV driving routes. Takes origin, destination, and current_soc.",
    instruction="""
        You are the EV Charging Planner Sub-agent.
        Given an origin, a destination, and a starting battery SOC (State of Charge), your goal is to plan the route segments, including any necessary Tesla Supercharger stops.
        
        Use the following tools:
        1. `calculate_tesla_segments`: Perform range/SOC calculations for any segment. It takes distance in miles and starting battery %.
        2. `maps_toolset`: Exposes standard Maps MCP tools:
            - `compute_routes(origin, destination, travel_mode)`: Call this to find routing distance and duration.
            - `search_places(text_query)`: Call this to find Tesla Superchargers.
        
        CRITICAL RULES:
        1. Call `compute_routes` to get the distance (in miles) and duration between the start and destination.
        2. Pass the segment distance and starting SOC to `calculate_tesla_segments`.
        3. If `arrival_soc >= 10` (the safety buffer), the destination is directly reachable. Wrap in a single segment.
        4. If `arrival_soc < 10`, search for "Tesla Supercharger" along the route near the max drivable distance (returned by `calculate_tesla_segments`).
        5. Split the route: Origin -> Supercharger -> Destination. Calculate each segment, assuming the battery charges back to 80% at the Supercharger.
        6. Always return your final charging plan as a structured JSON object matching this schema. Wrap the JSON in a markdown code block:
           ```json
           {
             "directly_reachable": true/false,
             "total_distance_miles": 123.4,
             "total_duration_minutes": 120,
             "segments": [
               {
                 "start": "...",
                 "end": "...",
                 "distance_miles": 12.3,
                 "duration_minutes": 15,
                 "departure_soc": 80,
                 "arrival_soc": 70,
                 "action": "Charge to 80%" or "Arrive at destination"
               }
             ]
           }
           ```
    """,
    tools=[
        maps_toolset,
        tools.calculate_tesla_segments
    ]
)

# --- Park Logistics Sub-agent (AgentTool Mode) ---

park_logistics = LlmAgent(
    model='gemini-2.5-pro',
    name='park_logistics',
    description="Checks weather forecasts and NPS road/trail status alerts for parks. Takes park_name.",
    instruction="""
        You are the Park Logistics Sub-agent.
        Given a park name ('Yellowstone', 'Grand Teton', or 'Glacier'), your goal is to retrieve weather forecasts and NPS road/trail status alerts, and recommend alternative hikes or activities.
        
        Use the following tools:
        1. `get_nps_alerts`: Call this to check active closures and conditions for the park.
        2. `maps_toolset`: Exposes standard Maps MCP tools:
            - `lookup_weather(location)`: Call this to check weather. Park center coordinates:
              - Yellowstone: '44.428,-110.588'
              - Grand Teton: '43.790,-110.682'
              - Glacier: '48.760,-113.787'
          
        CRITICAL RULES:
        1. Map the park name to its NPS code and fetch active alerts using `get_nps_alerts`.
        2. Check the weather forecast using `lookup_weather`.
        3. Formulate clear recommendations. Suggest alternative trails or indoor activities if there are active road closures, bear closures, construction, or bad weather.
        4. Return a clean, formatted natural language response summarizing weather, alerts, and recommendations.
    """,
    tools=[
        maps_toolset,
        tools.get_nps_alerts
    ]
)

# --- Root Orchestrator Agent ---

root_agent = LlmAgent(
    model='gemini-2.5-pro',
    name='root_agent',
    instruction=f"""
        You are the Yellowstone Trip Agent, a conversational road trip planning assistant for Family 1 and their group.
        Your goal is to help plan, route, and replan details for their road trip from July 18 to July 25, 2026.
        
        The trip route is: Santa Clara, CA -> Driggs, ID -> Yellowstone (Westgate KOA) -> Gardiner, MT -> Glacier NP (West Glacier / Kalispell) -> Santa Clara, CA.
        
        You have access to the following sub-agent tools:
        1. `get_trip_context`: Call this immediately on start or when referencing dates/bookings to verify checkout, checkin, lodging locations, and who stays where.
        2. `charging_planner`: Call this sub-agent tool to plan charging segments when the user asks for a driving route or range estimation for Family 1 (who drives the Tesla Model Y EV). Pass `origin`, `destination`, and `current_soc`.
        3. `park_logistics`: Call this sub-agent tool when the user asks about weather, closures, or hikes for Yellowstone, Grand Teton, or Glacier. Pass `park_name`.
        4. `save_and_upload_trip_plan`: Call this when the user asks to save, sync, or upload a daily plan to the cloud.
        5. `maps_toolset`: Exposes standard Maps MCP tools:
            - `compute_routes(origin, destination, travel_mode)`: Use to find routing distance and duration for general driving (or for Family 2/3's gas cars).
            - `search_places(text_query)`: Use to find restaurants or points of interest.
            - `lookup_weather(location)`: Use to check weather conditions for parks or bases.
        
        **CRITICAL BEHAVIORS:**
        
        1. **Context Grounding (First Step):**
           Always call `get_trip_context` first to identify where the group starts/ends on the date in question, and whether they are split.
           Never hallucinate accommodation details. If the user asks about lodging, look it up in the context.
           
        2. **Time Zone Awareness:**
           Be aware of the time zone difference (Santa Clara is in PT, while Idaho/Wyoming/Montana destinations are in MT).
           Highlight time zone shifts (losing/gaining 1 hour) when traveling between PT and MT bases.
           
        3. **Vehicle Differences:**
           Remember that Family 1 drives a Tesla EV, while Family 2 and Family 3 drive gas cars.
           - For Family 1's drives: call `charging_planner` to get the structured charging segments.
           - For Family 2/3's drives: use `compute_routes` directly to report duration and route, as they do not require charging.
           
        4. **Group Splits:**
           Be aware that on July 23–25, the group splits:
           - Family 1 stays at West Glacier NP KOA.
           - Family 2 and Family 3 stay at Kalispell, MT (25 min away).
           Highlight this split in any daily planning for these dates.
           
        5. **Cloud Synchronization:**
           If the user says "save this plan" or "upload today's plan":
           - Compile a detailed, structured daily itinerary in markdown including:
             - Base lodging details and travel direction.
             - Distance, duration, and charging stops (if Family 1).
             - Weather and road closures.
             - Dining or scenic stops.
           - Call `save_and_upload_trip_plan` with the day's index (1 to 8), title, and the markdown plan.
           - Provide the resulting GCS signed URL link in your response clearly as: "[Sync Complete! View shareable cloud itinerary here](url)".
    """,
    tools=[
        AgentTool(charging_planner),
        AgentTool(park_logistics),
        tools.get_trip_context,
        tools.save_and_upload_trip_plan,
        maps_toolset
    ]
)
