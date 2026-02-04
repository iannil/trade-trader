# coding=utf-8
"""
Unit tests for trade_trader.utils module.
"""
from decimal import Decimal
from datetime import datetime


class TestPriceRound:
    """Tests for price_round utility function."""

    def test_price_round_basic(self):
        """Test basic price rounding."""
        from trade_trader.utils import price_round

        # Test IF contract (0.2 tick) - uses banker's rounding
        base = Decimal('0.2')
        assert price_round(Decimal('1.3'), base) == Decimal('1.2')
        assert price_round(Decimal('1.5'), base) == Decimal('1.6')  # banker's rounding

        # Test cu contract (10 tick)
        base = Decimal('10')
        assert price_round(Decimal('68853'), base) == Decimal('68850')

    def test_price_round_edge_cases(self):
        """Test price rounding edge cases."""
        from trade_trader.utils import price_round

        base = Decimal('0.2')
        # 1.1 / 0.2 = 5.5, round(5.5) = 6 (banker's rounding), 6 * 0.2 = 1.2
        assert price_round(Decimal('1.1'), base) == Decimal('1.2')
        assert price_round(Decimal('1.0'), base) == Decimal('1.0')

    def test_price_round_with_float_input(self):
        """Test price rounding with float input."""
        from trade_trader.utils import price_round

        base = Decimal('0.2')
        # Float input is converted to Decimal, but may have precision issues
        # 1.3 as float = 1.300000000000000044..., rounds to 1.4
        assert price_round(1.3, base) == Decimal('1.4')
        # 1.5 as float = 1.5 exactly, rounds to 1.6 (banker's rounding: 7.5 -> 8)
        assert price_round(1.5, base) == Decimal('1.6')


class TestGetNextId:
    """Tests for get_next_id utility function."""

    def test_get_next_id_sequence(self):
        """Test get_next_id generates sequential IDs."""
        from trade_trader.utils import get_next_id

        # Reset the request_id
        if hasattr(get_next_id, "request_id"):
            delattr(get_next_id, "request_id")

        ids = [get_next_id() for _ in range(5)]
        assert ids == [1, 2, 3, 4, 5]

    def test_get_next_id_rollover(self):
        """Test get_next_id rolls over at 65535."""
        from trade_trader.utils import get_next_id

        get_next_id.request_id = 65534
        assert get_next_id() == 65535
        assert get_next_id() == 1


class TestStrToNumber:
    """Tests for str_to_number utility function."""

    def test_str_to_number_int(self):
        """Test converting int string to int."""
        from trade_trader.utils import str_to_number

        assert str_to_number("123") == 123

    def test_str_to_number_float(self):
        """Test converting float string to float."""
        from trade_trader.utils import str_to_number

        assert str_to_number("123.45") == 123.45

    def test_str_to_number_passthrough(self):
        """Test passthrough of non-string input."""
        from trade_trader.utils import str_to_number

        assert str_to_number(123) == 123
        assert str_to_number(123.45) == 123.45


class TestGetExpireDate:
    """Tests for get_expire_date utility function."""

    def test_get_expire_date_four_digit(self):
        """Test expire date with 4-digit year."""
        from trade_trader.utils import get_expire_date

        day = datetime(2024, 1, 15)
        assert get_expire_date('cu2501', day) == 2501

    def test_get_expire_date_two_digit(self):
        """Test expire date with 2-digit month (month-only code)."""
        from trade_trader.utils import get_expire_date

        day = datetime(2024, 1, 15)
        # year % 100 = 24, floor(24/10) = 2, so 01 + 2000 = 2001
        assert get_expire_date('cu01', day) == 2001

    def test_get_expire_date_year_rollover(self):
        """Test expire date year rollover in 2019."""
        from trade_trader.utils import get_expire_date

        day = datetime(2019, 12, 1)
        # year % 100 = 19, floor(19/10) = 1, so 01 + 1000 = 1001
        # But year % 10 = 9, so year_exact += 1, making it 2001
        assert get_expire_date('cu01', day) == 2001
