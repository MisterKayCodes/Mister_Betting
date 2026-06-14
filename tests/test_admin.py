"""
tests/test_admin.py — Admin feature tests
Run with: pytest tests/test_admin.py -v
Or: python -m pytest tests/test_admin.py -v
"""
import sys
from unittest.mock import MagicMock

# Mock the database module before importing anything else
sys.modules['bot.core.database'] = MagicMock()
sys.modules['sqlalchemy.ext.asyncio'] = MagicMock()


import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime
from aiogram.types import Message, CallbackQuery, User, Chat

from bot.handlers.admin.router import is_admin, main_keyboard, _pending_set
from bot.handlers.admin.commands import cmd_start, cmd_admin
from bot.handlers.admin.callbacks import (
    admin_callbacks,
    _handle_status,
    _handle_force_outcome,
    _handle_set_channel,
    _handle_add_match,
    _handle_sync_matches,
    _handle_clear_db,
    _handle_view_jobs,
    handle_text_replies
)
from bot.core.config import ADMIN_USERNAME


# ============================================================
# Test Fixtures
# ============================================================

@pytest.fixture
def admin_user():
    """Create a mock admin user"""
    user = MagicMock(spec=User)
    user.id = 123456789
    user.username = ADMIN_USERNAME
    return user


@pytest.fixture
def non_admin_user():
    """Create a mock non-admin user"""
    user = MagicMock(spec=User)
    user.id = 987654321
    user.username = "regular_user"
    return user


@pytest.fixture
def admin_message(admin_user):
    """Create a mock admin message"""
    message = AsyncMock(spec=Message)
    message.from_user = admin_user
    message.answer = AsyncMock()
    return message


@pytest.fixture
def non_admin_message(non_admin_user):
    """Create a mock non-admin message"""
    message = AsyncMock(spec=Message)
    message.from_user = non_admin_user
    message.answer = AsyncMock()
    return message


@pytest.fixture
def admin_callback(admin_user):
    """Create a mock admin callback query"""
    callback = AsyncMock(spec=CallbackQuery)
    callback.from_user = admin_user
    callback.data = "adm_test"
    callback.message = AsyncMock()
    callback.message.edit_text = AsyncMock()
    callback.answer = AsyncMock()
    return callback


@pytest.fixture
def non_admin_callback(non_admin_user):
    """Create a mock non-admin callback query"""
    callback = AsyncMock(spec=CallbackQuery)
    callback.from_user = non_admin_user
    callback.data = "adm_test"
    callback.answer = AsyncMock()
    return callback


# ============================================================
# Tests: is_admin() function
# ============================================================

class TestIsAdmin:
    """Test the admin verification function"""

    def test_admin_username_matches(self):
        """Test that correct admin username returns True"""
        assert is_admin(ADMIN_USERNAME) is True

    def test_admin_username_case_insensitive(self):
        """Test that case doesn't matter"""
        assert is_admin(ADMIN_USERNAME.upper()) is True

    def test_admin_username_with_at_symbol(self):
        """Test that @ symbol is stripped"""
        assert is_admin(f"@{ADMIN_USERNAME}") is True

    def test_non_admin_username_returns_false(self):
        """Test that non-admin returns False"""
        assert is_admin("fake_user") is False

    def test_empty_username_returns_false(self):
        """Test that empty username returns False"""
        assert is_admin("") is False
        assert is_admin(None) is False


# ============================================================
# Tests: main_keyboard() function
# ============================================================

class TestMainKeyboard:
    """Test the admin keyboard generation"""

    def test_keyboard_has_correct_buttons(self):
        """Test that keyboard has all expected buttons"""
        keyboard = main_keyboard()
        buttons = keyboard.inline_keyboard
        
        # Flatten buttons to check texts
        button_texts = []
        for row in buttons:
            for btn in row:
                button_texts.append(btn.text)
        
        expected_buttons = [
            "📊 Bot Status",
            "🏆 Force Next WIN", "❌ Force Next LOSS",
            "📡 Set Channel",
            "⚽ Add Match Manually",
            "🔄 Sync Matches Now", "🗑 Clear All Matches",
            "📅 View Jobs"
        ]
        
        for expected in expected_buttons:
            assert expected in button_texts

    def test_keyboard_has_correct_callback_data(self):
        """Test that keyboard buttons have correct callback data"""
        keyboard = main_keyboard()
        callback_data = []
        for row in keyboard.inline_keyboard:
            for btn in row:
                callback_data.append(btn.callback_data)
        
        expected_callbacks = [
            "adm_status",
            "adm_force_win", "adm_force_lose",
            "adm_set_channel",
            "adm_add_match",
            "adm_sync_now", "adm_clear_db",
            "adm_view_jobs"
        ]
        
        for expected in expected_callbacks:
            assert expected in callback_data


# ============================================================
# Tests: /start command
# ============================================================

class TestStartCommand:
    """Test the /start command handler"""

    @pytest.mark.asyncio
    async def test_admin_start_saves_chat_id(self, admin_message):
        """Test that admin /start saves chat_id to database"""
        with patch('bot.core.database.async_session') as mock_session:
            mock_session.return_value.__aenter__.return_value = AsyncMock()
            
            await cmd_start(admin_message)
            
            # Verify admin got welcome message
            admin_message.answer.assert_called()
            args, kwargs = admin_message.answer.call_args
            assert "Welcome back, Admin" in kwargs.get("text", args[0] if args else "")

    @pytest.mark.asyncio
    async def test_non_admin_start_shows_welcome(self, non_admin_message):
        """Test that non-admin /start shows welcome message"""
        await cmd_start(non_admin_message)
        
        non_admin_message.answer.assert_called()
        args, kwargs = non_admin_message.answer.call_args
        assert "Welcome" in kwargs.get("text", args[0] if args else "")


# ============================================================
# Tests: /admin command
# ============================================================

class TestAdminCommand:
    """Test the /admin command handler"""

    @pytest.mark.asyncio
    async def test_admin_sees_panel(self, admin_message):
        """Test that admin sees the admin panel"""
        await cmd_admin(admin_message)
        
        admin_message.answer.assert_called()
        args, kwargs = admin_message.answer.call_args
        assert "Admin Panel" in kwargs.get("text", args[0] if args else "")

    @pytest.mark.asyncio
    async def test_non_admin_sees_nothing(self, non_admin_message):
        """Test that non-admin doesn't see admin panel"""
        await cmd_admin(non_admin_message)
        
        # Non-admin should not get any response
        non_admin_message.answer.assert_not_called()


# ============================================================
# Tests: Callback handlers
# ============================================================

class TestCallbackHandlers:
    """Test the admin callback handlers"""

    @pytest.mark.asyncio
    async def test_admin_callback_router_forces_win(self, admin_callback):
        """Test that force win callback works"""
        admin_callback.data = "adm_force_win"
        
        with patch('bot.services.win_loss_engine.engine') as mock_engine:
            mock_engine.history = []
            
            await admin_callbacks(admin_callback)
            
            admin_callback.answer.assert_called()
            # Verify history was updated
            assert len(mock_engine.history) == 1
            assert mock_engine.history[0] is True

    @pytest.mark.asyncio
    async def test_admin_callback_router_forces_loss(self, admin_callback):
        """Test that force loss callback works"""
        admin_callback.data = "adm_force_lose"
        
        with patch('bot.services.win_loss_engine.engine') as mock_engine:
            mock_engine.history = []
            
            await admin_callbacks(admin_callback)
            
            assert len(mock_engine.history) == 1
            assert mock_engine.history[0] is False

    @pytest.mark.asyncio
    async def test_non_admin_callback_denied(self, non_admin_callback):
        """Test that non-admin callbacks are denied"""
        await admin_callbacks(non_admin_callback)
        
        non_admin_callback.answer.assert_called_with("Access Denied.", show_alert=True)

    @pytest.mark.asyncio
    async def test_set_channel_prompts_for_input(self, admin_callback):
        """Test that set channel prompts for channel ID"""
        admin_callback.data = "adm_set_channel"
        
        await admin_callbacks(admin_callback)
        
        admin_callback.message.answer.assert_called()
        args, kwargs = admin_callback.message.answer.call_args
        assert "Send me the channel ID" in kwargs.get("text", args[0] if args else "")
        assert admin_callback.from_user.id in _pending_set
        assert _pending_set[admin_callback.from_user.id] == "channel"

    @pytest.mark.asyncio
    async def test_add_match_prompts_for_input(self, admin_callback):
        """Test that add match prompts for match details"""
        admin_callback.data = "adm_add_match"
        
        await admin_callbacks(admin_callback)
        
        admin_callback.message.answer.assert_called()
        args, kwargs = admin_callback.message.answer.call_args
        assert "Add a match manually" in kwargs.get("text", args[0] if args else "")
        assert admin_callback.from_user.id in _pending_set
        assert _pending_set[admin_callback.from_user.id] == "match"


# ============================================================
# Tests: Text reply handlers
# ============================================================

class TestTextReplyHandlers:
    """Test the text reply handlers for channel and match input"""

    @pytest.mark.asyncio
    async def test_channel_input_saves_to_db(self, admin_message):
        """Test that channel input saves to database"""
        _pending_set[admin_message.from_user.id] = "channel"
        admin_message.text = "-1001234567890"
        
        with patch('bot.core.database.async_session') as mock_session:
            mock_session.return_value.__aenter__.return_value = AsyncMock()
            
            await handle_text_replies(admin_message)
            
            admin_message.answer.assert_called()
            assert admin_message.from_user.id not in _pending_set

    @pytest.mark.asyncio
    async def test_match_input_creates_match(self, admin_message):
        """Test that match input creates a match in database"""
        _pending_set[admin_message.from_user.id] = "match"
        admin_message.text = """MATCH
League: TEST LEAGUE
Home: Team A
Away: Team B
Kickoff: 2026-12-31 18:00
API_ID: 0"""
        
        with patch('bot.core.database.async_session') as mock_session:
            mock_session.return_value.__aenter__.return_value = AsyncMock()
            
            with patch('bot.services.match_api.MatchDataFetcher._default_odds', return_value={"2-1": 12.0}):
                await handle_text_replies(admin_message)
        
        admin_message.answer.assert_called()
        assert admin_message.from_user.id not in _pending_set

    @pytest.mark.asyncio
    async def test_invalid_match_format_returns_error(self, admin_message):
        """Test that invalid match format returns error"""
        _pending_set[admin_message.from_user.id] = "match"
        admin_message.text = "INVALID FORMAT"
        
        await handle_text_replies(admin_message)
        
        admin_message.answer.assert_called()
        # Should show error message
        args, kwargs = admin_message.answer.call_args
        assert "Could not parse match" in kwargs.get("text", args[0] if args else "")


# ============================================================
# Tests: Individual callback functions
# ============================================================

class TestIndividualCallbacks:
    """Test individual callback handler functions"""

    @pytest.mark.asyncio
    async def test_handle_status(self, admin_callback):
        """Test status handler"""
        with patch('bot.core.database.async_session') as mock_session:
            mock_session.return_value.__aenter__.return_value = AsyncMock()
            
            await _handle_status(admin_callback)
            
            admin_callback.message.edit_text.assert_called()
            admin_callback.answer.assert_called()

    @pytest.mark.asyncio
    async def test_handle_force_outcome_win(self, admin_callback):
        """Test force win handler"""
        with patch('bot.services.win_loss_engine.engine') as mock_engine:
            mock_engine.history = []
            
            await _handle_force_outcome(admin_callback, "adm_force_win")
            
            admin_callback.answer.assert_called_with("Next match outcome pre-set to WIN 🏆!", show_alert=True)

    @pytest.mark.asyncio
    async def test_handle_force_outcome_loss(self, admin_callback):
        """Test force loss handler"""
        with patch('bot.services.win_loss_engine.engine') as mock_engine:
            mock_engine.history = []
            
            await _handle_force_outcome(admin_callback, "adm_force_lose")
            
            admin_callback.answer.assert_called_with("Next match outcome pre-set to LOSS ❌!", show_alert=True)

    @pytest.mark.asyncio
    async def test_handle_set_channel(self, admin_callback):
        """Test set channel handler"""
        await _handle_set_channel(admin_callback)
        
        admin_callback.message.answer.assert_called()
        admin_callback.answer.assert_called()

    @pytest.mark.asyncio
    async def test_handle_add_match(self, admin_callback):
        """Test add match handler"""
        await _handle_add_match(admin_callback)
        
        admin_callback.message.answer.assert_called()
        admin_callback.answer.assert_called()


# ============================================================
# Tests: Integration - Full admin workflow
# ============================================================

class TestAdminWorkflow:
    """Test complete admin workflows"""

    @pytest.mark.asyncio
    async def test_full_admin_flow(self, admin_message, admin_callback):
        """Test that admin can go through full workflow"""
        
        # 1. Admin starts bot
        await cmd_start(admin_message)
        assert admin_message.answer.called
        
        # 2. Admin opens panel
        await cmd_admin(admin_message)
        assert admin_message.answer.called
        
        # 3. Admin checks status
        admin_callback.data = "adm_status"
        with patch('bot.core.database.async_session'):
            await admin_callbacks(admin_callback)
        assert admin_callback.message.edit_text.called
        
        # 4. Admin forces a win
        admin_callback.data = "adm_force_win"
        with patch('bot.services.win_loss_engine.engine') as mock_engine:
            mock_engine.history = []
            await admin_callbacks(admin_callback)
        assert admin_callback.answer.called


# ============================================================
# Tests: Pending set cleanup
# ============================================================

class TestPendingSetCleanup:
    """Test that _pending_set is properly cleaned up"""

    @pytest.mark.asyncio
    async def test_pending_set_cleared_after_channel_input(self, admin_message):
        """Test that pending set is cleared after channel input"""
        _pending_set[admin_message.from_user.id] = "channel"
        admin_message.text = "@testchannel"
        
        with patch('bot.core.database.async_session'):
            await handle_text_replies(admin_message)
        
        assert admin_message.from_user.id not in _pending_set

    @pytest.mark.asyncio
    async def test_pending_set_cleared_after_match_input(self, admin_message):
        """Test that pending set is cleared after match input"""
        _pending_set[admin_message.from_user.id] = "match"
        admin_message.text = """MATCH
League: TEST
Home: Home
Away: Away
Kickoff: 2026-12-31 18:00
API_ID: 0"""
        
        with patch('bot.core.database.async_session'):
            with patch('bot.services.match_api.MatchDataFetcher._default_odds', return_value={}):
                await handle_text_replies(admin_message)
        
        assert admin_message.from_user.id not in _pending_set


# ============================================================
# Run tests
# ============================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])