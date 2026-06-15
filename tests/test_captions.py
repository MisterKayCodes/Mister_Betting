import os
import sys

# Add parent directory to path so bot imports work
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio
from bot.services.caption_engine import get_caption


def test_captions():
    admin = "opozdal96"
    print("====================================")
    print("Testing Step 1 (Preview) Caption:")
    print("====================================")
    print(asyncio.run(get_caption("preview", admin)))
    
    print("\n====================================")
    print("Testing Step 2 (Urgency) Caption:")
    print("====================================")
    print(asyncio.run(get_caption("urgency", admin)))
    
    print("\n====================================")
    print("Testing Step 3 (Win) Caption:")
    print("====================================")
    print(asyncio.run(get_caption("win", admin)))

    print("\n====================================")
    print("Testing Step 3 (Lose) Caption:")
    print("====================================")
    print(asyncio.run(get_caption("lose", admin)))

if __name__ == "__main__":
    test_captions()
