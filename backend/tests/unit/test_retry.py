import pytest

from app.core.retry import retry_async


class TestRetry:
    @pytest.mark.asyncio
    async def test_succeeds_first_try(self):
        call_count = 0

        async def success():
            nonlocal call_count
            call_count += 1
            return "ok"

        result = await retry_async(success, max_retries=3, base_delay=0.01)
        assert result == "ok"
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_retries_on_failure_then_succeeds(self):
        call_count = 0

        async def flaky():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ValueError("not yet")
            return "ok"

        result = await retry_async(flaky, max_retries=3, base_delay=0.01)
        assert result == "ok"
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_exhausts_retries(self):
        async def always_fail():
            raise ValueError("nope")

        with pytest.raises(ValueError, match="nope"):
            await retry_async(always_fail, max_retries=2, base_delay=0.01)

    @pytest.mark.asyncio
    async def test_only_retries_specified_exceptions(self):
        call_count = 0

        async def wrong_error():
            nonlocal call_count
            call_count += 1
            raise TypeError("wrong type")

        with pytest.raises(TypeError):
            await retry_async(
                wrong_error,
                max_retries=3,
                base_delay=0.01,
                exceptions=(ValueError,),
            )
        assert call_count == 1  # No retries for TypeError
