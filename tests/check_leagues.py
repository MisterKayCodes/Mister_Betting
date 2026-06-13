import asyncio
import aiohttp
from datetime import datetime
import os
from dotenv import load_dotenv

load_dotenv()
API_FOOTBALL_KEY = os.environ.get("API_FOOTBALL_KEY")

async def check_leagues():
    headers = {
        "x-rapidapi-host": "v3.football.api-sports.io",
        "x-rapidapi-key": API_FOOTBALL_KEY,
    }
    today = datetime.utcnow().strftime("%Y-%m-%d")
    url = "https://v3.football.api-sports.io/fixtures"
    params = {"date": today}
    
    async with aiohttp.ClientSession(headers=headers) as session:
        async with session.get(url, params=params) as resp:
            data = await resp.json()
            leagues = {}
            for f in data.get("response", []):
                l_id = f["league"]["id"]
                l_name = f["league"]["name"]
                l_country = f["league"]["country"]
                leagues[l_id] = f"{l_country} - {l_name}"
            
            print(f"Found {len(data.get('response', []))} matches today across {len(leagues)} leagues.")
            print("Sample active leagues today:")
            for i, (lid, lname) in enumerate(leagues.items()):
                print(f"ID: {lid} | {lname}")
                if i > 20: break

asyncio.run(check_leagues())
