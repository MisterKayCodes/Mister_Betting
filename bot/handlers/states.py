# bot/handlers/states.py
from aiogram.fsm.state import State, StatesGroup

class AdminStates(StatesGroup):
    waiting_for_channel = State()  # Waiting for channel ID input
    waiting_for_match = State()    # Waiting for manual match input
    waiting_for_hype_link = State() # Waiting for custom post link/ID for hype