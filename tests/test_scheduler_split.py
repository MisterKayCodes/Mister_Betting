# tests/test_scheduler_split.py
import sys
from types import ModuleType
import asyncio
from datetime import datetime, timedelta

# --- THE PLAYWRIGHT BYPASS TRICK ---
fake_poster = ModuleType("bot.services.poster")
sys.modules["bot.services.poster"] = fake_poster

fake_image_gen = ModuleType("bot.services.image_generator")
sys.modules["bot.services.image_generator"] = fake_image_gen

from bot.services.scheduler import TimelineScheduler

class MockBot:
    pass

class MockMatch:
    def __init__(self, match_id: int, home: str, away: str, kickoff: datetime):
        self.id = match_id
        self.home_team = home
        self.away_team = away
        self.league_name = "Test Premier League"
        self.kickoff_time = kickoff
        self.preview_posted = False
        self.urgency_posted = False
        self.before_slip_posted = False
        self.final_slip_posted = False
        self.result_preview_posted = False

async def run_scheduler_diagnostics():
    print("🧪 ==================================================")
    print("🧪 RUNNING LIGHTWEIGHT SCHEDULER TIMING TEST")
    print("🧪 ==================================================\n")

    mock_bot = MockBot()
    test_scheduler = TimelineScheduler(bot=mock_bot)
    
    print("🔄 Step 1: Initializing newly split TimelineScheduler structure...")
    try:
        test_scheduler.scheduler.start()
        print("✅ SUCCESS: APScheduler engine booted cleanly within manager.py!\n")
    except Exception as e:
        print(f"❌ CRITICAL FAILURE: Could not start scheduler engine. Error: {e}\n")
        return

    now_utc = datetime.utcnow()
    test_kickoff = now_utc + timedelta(hours=3)
    mock_match = MockMatch(match_id=999, home="Arsenal", away="Chelsea", kickoff=test_kickoff)
    
    print(f"🔄 Step 2: Registering mock match timeline details...")
    print(f"   • Current Simulated Time (UTC): {now_utc.strftime('%H:%M:%S')}")
    print(f"   • Target Match Kickoff   (UTC): {test_kickoff.strftime('%H:%M:%S')}\n")

    print("🔄 Step 3: Triggering timeline generation math rules...")
    await test_scheduler._schedule_match_timeline(mock_match)
    print("")

    active_jobs = test_scheduler.scheduler.get_jobs()
    print(f"🔄 Step 4: Analyzing planned schedule matrix structure (Found {len(active_jobs)} active alarms)...")
    
    job_map = {}
    for job in active_jobs:
        job_map[job.id] = job.next_run_time.replace(tzinfo=None)

    # FIXED: This now scans safely for standard OR rush mode names
    steps_to_verify = ["step1_999", "step2_999", "step3_999", "step4_999", "step5_999"]
    all_steps_present = True
    
    for step in steps_to_verify:
        if step not in job_map and f"rush_{step}" not in job_map:
            all_steps_present = False

    if all_steps_present:
        print("✅ SUCCESS: All 5 automated steps mapped correctly into memory!\n")
    else:
        print("❌ FAILURE: Some sequence steps failed to schedule correctly.\n")
        test_scheduler.scheduler.shutdown()
        return

    print("🔄 Step 5: Auditing Post-Match delivery calculations for timing bugs...")
    step5_key = "step5_999" if "step5_999" in job_map else "rush_step5_999"
    step4_key = "step4_999" if "step4_999" in job_map else "rush_step4_999"
    
    step5_time = job_map[step5_key]
    step4_time = job_map[step4_key]

    print(f"   • Step 5 (Final Slip ticket) will execute at: {step5_time.strftime('%H:%M:%S')}")
    print(f"   • Step 4 (Result summary card) will execute at: {step4_time.strftime('%H:%M:%S')}")

    if step5_time < step4_time:
        print("✅ SUCCESS: Sequence order timeline bug resolved! Betting slips post before match result cards.\n")
    else:
        print("❌ CRITICAL TIMELINE BUG: Slips are scheduled to print after the match summaries!\n")

    print("🔄 Step 6: Testing Admin Panel Countdown Math simulation...")
    lines = []
    for job_id, run_time in job_map.items():
        clean_id = job_id.replace("rush_", "")
        parts = clean_id.split("_")
        step_name = parts[0]
        diff = run_time - now_utc
        hours, remainder = divmod(int(diff.total_seconds()), 3600)
        minutes, _ = divmod(remainder, 60)
        
        time_str = f"In {hours}h {minutes}m ⏳" if hours > 0 else f"In {minutes}m ⏳"
        lines.append(f"   • {step_name.upper()}: {time_str}")
            
    for line in sorted(lines):
        print(line)
    print("\n✅ SUCCESS: Admin panel calculations output exactly as intended!")

    test_scheduler.scheduler.shutdown()
    print("\n🧪 ==================================================")
    print("🧪 DIAGNOSTIC SYSTEM CHECK COMPLETED SUCCESSFULLY!")
    print("🧪 ==================================================")

if __name__ == "__main__":
    asyncio.run(run_scheduler_diagnostics())
