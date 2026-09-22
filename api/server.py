import uvicorn
from fastapi import FastAPI, Query
from sqlalchemy import select
from loguru import logger

from bot.core.database import async_session, Match

app = FastAPI(title="Mister Betting API", version="1.0.0")


@app.get("/api/v1/empire-ledger")
async def get_empire_ledger(limit: int = Query(50, ge=1, le=200)):
    """
    👑 Empire Standard Ledger Route for Mister Betting.
    Synthesizes match steps and post flags into unified action records for Mister Chief aggregation.
    """
    try:
        async with async_session() as session:
            stmt = (
                select(Match)
                .order_by(Match.kickoff_time.desc(), Match.id.desc())
                .limit(limit)
            )
            result = await session.execute(stmt)
            matches = result.scalars().all()

            entries = []
            total_wins = 0
            total_losses = 0
            pending_matches = 0

            for match in matches:
                title = f"{match.home_team or 'Home'} vs {match.away_team or 'Away'}"
                league = match.league_name or "General"
                kickoff_str = match.kickoff_time.strftime("%Y-%m-%d %H:%M:%S") if match.kickoff_time else ""

                if match.is_finished:
                    if match.is_win:
                        total_wins += 1
                    else:
                        total_losses += 1
                else:
                    pending_matches += 1

                # Generate ledger entries for each posted step on this match
                # 1. Preview Card
                if match.preview_posted:
                    entries.append({
                        "service": "mister_betting",
                        "campaign": league,
                        "target_type": "CHANNEL",
                        "target_name": title,
                        "action": "MATCH PREVIEW",
                        "session": "mister_betting",
                        "status": "SUCCESS",
                        "error": None,
                        "timestamp": kickoff_str
                    })

                # 2. Urgency Alert
                if match.urgency_posted:
                    entries.append({
                        "service": "mister_betting",
                        "campaign": league,
                        "target_type": "CHANNEL",
                        "target_name": title,
                        "action": "URGENCY ALERT",
                        "session": "mister_betting",
                        "status": "SUCCESS",
                        "error": None,
                        "timestamp": kickoff_str
                    })

                # 3. Final Slip
                if match.final_slip_posted or match.before_slip_posted:
                    entries.append({
                        "service": "mister_betting",
                        "campaign": league,
                        "target_type": "CHANNEL",
                        "target_name": title,
                        "action": "VIP SLIP",
                        "session": "mister_betting",
                        "status": "SUCCESS",
                        "error": None,
                        "timestamp": kickoff_str
                    })

                # 4. Result Verified
                if match.is_finished:
                    st_label = "WIN 🟢" if match.is_win else "LOSS 🔴"
                    entries.append({
                        "service": "mister_betting",
                        "campaign": league,
                        "target_type": "CHANNEL",
                        "target_name": title,
                        "action": f"RESULT ({st_label})",
                        "session": "mister_betting",
                        "status": "SUCCESS",
                        "error": match.skip_reason,
                        "timestamp": kickoff_str
                    })

                # 5. Testimonial
                if match.testimonial_posted:
                    entries.append({
                        "service": "mister_betting",
                        "campaign": league,
                        "target_type": "CHANNEL",
                        "target_name": title,
                        "action": "TESTIMONIAL",
                        "session": "mister_betting",
                        "status": "SUCCESS",
                        "error": None,
                        "timestamp": kickoff_str
                    })

                # 6. Stuck / Failed score fetch
                if match.result_fetch_retries >= 3 and not match.is_finished:
                    entries.append({
                        "service": "mister_betting",
                        "campaign": league,
                        "target_type": "CHANNEL",
                        "target_name": title,
                        "action": "SCORE FETCH",
                        "session": "mister_betting",
                        "status": "FAILED",
                        "error": match.skip_reason or f"Missing score ({match.result_fetch_retries} retries)",
                        "timestamp": kickoff_str
                    })

            # Sort entries newest timestamp first
            entries.sort(key=lambda x: str(x.get("timestamp", "")), reverse=True)

            return {
                "service": "mister_betting",
                "total": len(entries),
                "stats": {
                    "total_matches": len(matches),
                    "wins": total_wins,
                    "losses": total_losses,
                    "pending": pending_matches
                },
                "entries": entries[:limit]
            }
    except Exception as e:
        logger.error(f"[BETTING LEDGER API] Error querying empire ledger: {e}")
        return {"service": "mister_betting", "total": 0, "entries": [], "stats": {}}


async def run_api_server(host: str = "0.0.0.0", port: int = 8015):
    """Run uvicorn server programmatically on port 8015."""
    config = uvicorn.Config(app=app, host=host, port=port, log_level="warning")
    server = uvicorn.Server(config)
    logger.info(f"👑 Mister Betting Empire Ledger API starting on http://{host}:{port}/api/v1/empire-ledger")
    await server.serve()
