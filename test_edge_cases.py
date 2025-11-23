import unittest
import asyncio
import os
from unittest.mock import MagicMock, AsyncMock, patch

# Mock env before imports
os.environ["ENCRYPTION_KEY"] = "0SoYb1MCRG5oyyZZaqKqyGBkHV-hxdj40JLjgPxn398="

from bot import is_valid_wallet
# We need to import executor but it imports ClobClient which might fail if not installed or mocked?
# It is installed in venv.
import executor

class TestEdgeCases(unittest.TestCase):
    def test_wallet_validation(self):
        print("\nTesting Wallet Validation Edge Cases...")
        # Valid
        self.assertTrue(is_valid_wallet("0x1234567890123456789012345678901234567890"))
        # Invalid length (too short)
        self.assertFalse(is_valid_wallet("0x123"))
        # Invalid length (too long)
        self.assertFalse(is_valid_wallet("0x12345678901234567890123456789012345678901"))
        # Invalid chars (Z is not hex)
        self.assertFalse(is_valid_wallet("0xZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZ"))
        # No prefix
        self.assertFalse(is_valid_wallet("1234567890123456789012345678901234567890"))
        # Empty
        self.assertFalse(is_valid_wallet(""))
        # Whitespace
        self.assertTrue(is_valid_wallet("  0x1234567890123456789012345678901234567890  "))
        print("✅ Wallet validation tests passed")

class TestExecutorEdgeCases(unittest.IsolatedAsyncioTestCase):
    @patch("executor.log_and_notify")
    @patch("executor.ClobClient")
    @patch("executor.AsyncSessionLocal")
    @patch("executor.decrypt_data")
    async def test_empty_order_book(self, mock_decrypt, mock_db_cls, mock_client_cls, mock_log):
        print("\nTesting Trade Execution: Empty Order Book...")
        
        # Setup Job
        job_queue = asyncio.Queue()
        job = {
            "subscription_id": 1,
            "user_id": 123,
            "trade_amount_usdc": 10.0,
            "source_market_id": "mkt1",
            "source_outcome_index": 0,
            "source_side": "BUY",
            "source_trade_hash": "hash1"
        }
        await job_queue.put(job)
        
        # Setup Mocks
        mock_decrypt.return_value = "dummy_key"
        
        mock_session = AsyncMock()
        mock_db_cls.return_value.__aenter__.return_value = mock_session
        mock_keys = MagicMock()
        mock_keys.api_key = "enc"
        mock_keys.api_secret = "enc"
        mock_keys.api_passphrase = "enc"
        mock_session.get.return_value = mock_keys
        
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        # Return empty order book
        mock_client.get_order_book.return_value = MagicMock(asks=[], bids=[])
        
        # Mock job_queue.get to return job once then cancel
        original_get = job_queue.get
        async def side_effect():
            if job_queue.empty():
                raise asyncio.CancelledError("Stop worker")
            return await original_get()
        
        job_queue.get = side_effect
        
        # Run Worker
        try:
            await executor.trade_execution_worker(job_queue, bot=MagicMock())
        except asyncio.CancelledError:
            pass
        
        # Verify
        # Should have called log_and_notify with FAILED status
        # args: bot, user_id, sub_id, status, job, error
        call_args = mock_log.call_args
        self.assertIsNotNone(call_args, "log_and_notify was not called")
        args, _ = call_args
        self.assertEqual(args[3], "FAILED")
        self.assertIn("Could not determine market price", args[5])
        print("✅ Empty order book handled correctly (FAILED status logged)")

    @patch("executor.log_and_notify")
    @patch("executor.ClobClient")
    @patch("executor.AsyncSessionLocal")
    @patch("executor.decrypt_data")
    async def test_api_error(self, mock_decrypt, mock_db_cls, mock_client_cls, mock_log):
        print("\nTesting Trade Execution: API Error...")
        
        # Setup Job
        job_queue = asyncio.Queue()
        job = {
            "subscription_id": 1,
            "user_id": 123,
            "trade_amount_usdc": 10.0,
            "source_market_id": "mkt1",
            "source_outcome_index": 0,
            "source_side": "BUY",
            "source_trade_hash": "hash1"
        }
        await job_queue.put(job)
        
        # Setup Mocks
        mock_decrypt.return_value = "dummy_key"
        mock_session = AsyncMock()
        mock_db_cls.return_value.__aenter__.return_value = mock_session
        mock_session.get.return_value = MagicMock()
        
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client.get_order_book.side_effect = Exception("API Connection Timeout")
        
        # Mock queue
        original_get = job_queue.get
        async def side_effect():
            if job_queue.empty():
                raise asyncio.CancelledError("Stop worker")
            return await original_get()
        job_queue.get = side_effect
        
        # Run
        try:
            await executor.trade_execution_worker(job_queue, bot=MagicMock())
        except asyncio.CancelledError:
            pass
            
        # Verify
        call_args = mock_log.call_args
        self.assertIsNotNone(call_args)
        args, _ = call_args
        self.assertEqual(args[3], "FAILED")
        self.assertIn("API Connection Timeout", args[5])
        print("✅ API Error handled correctly")

if __name__ == "__main__":
    unittest.main()
