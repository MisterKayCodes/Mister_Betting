import asyncio
import os
import sys

# Add parent directory to path so bot imports work
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bot.services.image_generator import ImageGenerator

def read_data_file():
    data = {}
    filepath = os.path.join(os.path.dirname(__file__), "data_img.txt")
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            if "=" in line:
                key, val = line.strip().split("=", 1)
                
                # Convert types automatically
                if val.lower() == "true": val = True
                elif val.lower() == "false": val = False
                elif key in ["homeScore", "awayScore", "claimedHomeScore", "claimedAwayScore"]:
                    val = int(val)
                elif key in ["stake", "odds", "payout", "balance", "cashout"]:
                    val = float(val)
                    
                data[key] = val
    return data

async def test_images():
    print("Testing Image Generator from data_img.txt...")
    gen = ImageGenerator()
    
    # Read dynamic data
    mock_data = read_data_file()
    
    print("1. Generating 'Preview Before' image...")
    await gen.generate_image("preview-before", mock_data, "test_preview_before.png")
    
    print("2. Generating 'Black Box Slip' image...")
    mock_data["hideOdds"] = True
    await gen.generate_image("slip-before", mock_data, "test_slip_before.png")
    
    print("3. Generating 'Slip Won' image...")
    mock_data["hideOdds"] = False
    await gen.generate_image("slip-won", mock_data, "test_slip_won.png")
    
    print("\n✅ Done! Check the 'output_images' folder in your project root.")

if __name__ == "__main__":
    asyncio.run(test_images())
