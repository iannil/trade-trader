# coding=utf-8
"""
技术指标库 - Technical Indicators Library

提供常用技术指标计算功能：
- 趋势指标: MA, EMA, MACD, DMI, TRIX, BRAR
- 动量指标: RSI, KDJ, CCI, WR, ROC
- 波动指标: ATR, BB (布林带)
- 成交量指标: OBV, VOL_MA
"""
from typing import List, Optional, Tuple
import logging
import numpy as np
import pandas as pd


logger = logging.getLogger('IndicatorLibrary')


class IndicatorLibrary:
    """
    技术指标库

    封装常用技术指标的计算方法
    """

    @staticmethod
    def sma(series: pd.Series, period: int) -> pd.Series:
        """
        简单移动平均 (Simple Moving Average)

        Args:
            series: 价格序列
            period: 周期

        Returns:
            pd.Series: SMA值
        """
        return series.rolling(window=period).mean()

    @staticmethod
    def ema(series: pd.Series, period: int) -> pd.Series:
        """
        指数移动平均 (Exponential Moving Average)

        Args:
            series: 价格序列
            period: 周期

        Returns:
            pd.Series: EMA值
        """
        return series.ewm(span=period, adjust=False).mean()

    @staticmethod
    def macd(
        series: pd.Series,
        fast_period: int = 12,
        slow_period: int = 26,
        signal_period: int = 9
    ) -> Tuple[pd.Series, pd.Series, pd.Series]:
        """
        MACD指标 (Moving Average Convergence Divergence)

        Args:
            series: 价格序列
            fast_period: 快线周期
            slow_period: 慢线周期
            signal_period: 信号线周期

        Returns:
            Tuple[pd.Series, pd.Series, pd.Series]: (MACD, Signal, Histogram)
        """
        ema_fast = series.ewm(span=fast_period, adjust=False).mean()
        ema_slow = series.ewm(span=slow_period, adjust=False).mean()

        macd_line = ema_fast - ema_slow
        signal_line = macd_line.ewm(span=signal_period, adjust=False).mean()
        histogram = macd_line - signal_line

        return macd_line, signal_line, histogram

    @staticmethod
    def rsi(series: pd.Series, period: int = 14) -> pd.Series:
        """
        RSI指标 (Relative Strength Index)

        Args:
            series: 价格序列
            period: 周期

        Returns:
            pd.Series: RSI值
        """
        delta = series.diff()
        gain = delta.where(delta > 0, 0)
        loss = -delta.where(delta < 0, 0)

        avg_gain = gain.rolling(window=period).mean()
        avg_loss = loss.rolling(window=period).mean()

        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))

        return rsi

    @staticmethod
    def kdj(
        high: pd.Series,
        low: pd.Series,
        close: pd.Series,
        n: int = 9,
        m1: int = 3,
        m2: int = 3
    ) -> Tuple[pd.Series, pd.Series, pd.Series]:
        """
        KDJ指标 (随机指标)

        Args:
            high: 最高价序列
            low: 最低价序列
            close: 收盘价序列
            n: RSV周期
            m1: K平滑周期
            m2: D平滑周期

        Returns:
            Tuple[pd.Series, pd.Series, pd.Series]: (K, D, J)
        """
        low_n = low.rolling(window=n).min()
        high_n = high.rolling(window=n).max()

        rsv = (close - low_n) / (high_n - low_n) * 100

        k = rsv.ewm(com=m1, adjust=False).mean()
        d = k.ewm(com=m2, adjust=False).mean()
        j = 3 * k - 2 * d

        return k, d, j

    @staticmethod
    def cci(
        high: pd.Series,
        low: pd.Series,
        close: pd.Series,
        period: int = 20
    ) -> pd.Series:
        """
        CCI指标 (Commodity Channel Index)

        Args:
            high: 最高价序列
            low: 最低价序列
            close: 收盘价序列
            period: 周期

        Returns:
            pd.Series: CCI值
        """
        tp = (high + low + close) / 3
        ma_tp = tp.rolling(window=period).mean()
        md = tp.rolling(window=period).apply(
            lambda x: np.abs(x - x.mean()).mean()
        )

        cci = (tp - ma_tp) / (0.015 * md)

        return cci

    @staticmethod
    def atr(
        high: pd.Series,
        low: pd.Series,
        close: pd.Series,
        period: int = 14
    ) -> pd.Series:
        """
        ATR指标 (Average True Range)

        Args:
            high: 最高价序列
            low: 最低价序列
            close: 收盘价序列
            period: 周期

        Returns:
            pd.Series: ATR值
        """
        prev_close = close.shift(1)

        tr1 = high - low
        tr2 = abs(high - prev_close)
        tr3 = abs(low - prev_close)

        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

        atr = tr.rolling(window=period).mean()

        return atr

    @staticmethod
    def bollinger_bands(
        series: pd.Series,
        period: int = 20,
        std_dev: float = 2.0
    ) -> Tuple[pd.Series, pd.Series, pd.Series]:
        """
        布林带 (Bollinger Bands)

        Args:
            series: 价格序列
            period: 周期
            std_dev: 标准差倍数

        Returns:
            Tuple[pd.Series, pd.Series, pd.Series]: (上轨, 中轨, 下轨)
        """
        middle = series.rolling(window=period).mean()
        std = series.rolling(window=period).std()

        upper = middle + std_dev * std
        lower = middle - std_dev * std

        return upper, middle, lower

    @staticmethod
    def obv(series: pd.Series, volume: pd.Series) -> pd.Series:
        """
        OBV指标 (On Balance Volume)

        Args:
            series: 价格序列
            volume: 成交量序列

        Returns:
            pd.Series: OBV值
        """
        obv = (np.sign(series.diff()) * volume).fillna(0).cumsum()
        return obv

    @staticmethod
    def williams_r(
        high: pd.Series,
        low: pd.Series,
        close: pd.Series,
        period: int = 14
    ) -> pd.Series:
        """
        威廉指标 (Williams %R)

        Args:
            high: 最高价序列
            low: 最低价序列
            close: 收盘价序列
            period: 周期

        Returns:
            pd.Series: %R值
        """
        high_n = high.rolling(window=period).max()
        low_n = low.rolling(window=period).min()

        r = (high_n - close) / (high_n - low_n) * -100

        return r

    @staticmethod
    def dmi(
        high: pd.Series,
        low: pd.Series,
        close: pd.Series,
        period: int = 14
    ) -> Tuple[pd.Series, pd.Series, pd.Series]:
        """
        DMI指标 (Directional Movement Index)

        Args:
            high: 最高价序列
            low: 最低价序列
            close: 收盘价序列
            period: 周期

        Returns:
            Tuple[pd.Series, pd.Series, pd.Series]: (PDI, MDI, ADX)
        """
        up = high - high.shift(1)
        down = low.shift(1) - low

        plus_dm = up.where((up > 0) & (down <= 0), 0).rolling(window=period).sum()
        minus_dm = down.where((down > 0) & (up <= 0), 0).rolling(window=period).sum()

        tr = pd.concat([
            high - low,
            abs(high - close.shift(1)),
            abs(low - close.shift(1))
        ], axis=1).max(axis=1)

        plus_di = 100 * plus_dm / tr.rolling(window=period).sum()
        minus_di = 100 * minus_dm / tr.rolling(window=period).sum()

        dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di)
        adx = dx.rolling(window=period).mean()

        return plus_di, minus_di, adx

    @staticmethod
    def trix(series: pd.Series, period: int = 12) -> pd.Series:
        """
        TRIX指标 (三重指数平滑移动平均)

        Args:
            series: 价格序列
            period: 周期

        Returns:
            pd.Series: TRIX值
        """
        ema1 = series.ewm(span=period, adjust=False).mean()
        ema2 = ema1.ewm(span=period, adjust=False).mean()
        ema3 = ema2.ewm(span=period, adjust=False).mean()

        trix = ema3.pct_change() * 100

        return trix

    @staticmethod
    def calculate_all(
        df: pd.DataFrame,
        price_col: str = 'close'
    ) -> pd.DataFrame:
        """
        计算所有技术指标

        Args:
            df: K线数据，包含 open, high, low, close, volume 列
            price_col: 价格列名

        Returns:
            pd.DataFrame: 包含所有指标的DataFrame
        """
        if df.empty:
            return df

        result = df.copy()

        # 趋势指标
        result['sma_5'] = IndicatorLibrary.sma(result[price_col], 5)
        result['sma_10'] = IndicatorLibrary.sma(result[price_col], 10)
        result['sma_20'] = IndicatorLibrary.sma(result[price_col], 20)
        result['sma_60'] = IndicatorLibrary.sma(result[price_col], 60)

        result['ema_5'] = IndicatorLibrary.ema(result[price_col], 5)
        result['ema_10'] = IndicatorLibrary.ema(result[price_col], 10)
        result['ema_20'] = IndicatorLibrary.ema(result[price_col], 20)

        macd, signal, hist = IndicatorLibrary.macd(result[price_col])
        result['macd'] = macd
        result['macd_signal'] = signal
        result['macd_hist'] = hist

        # 动量指标
        result['rsi_6'] = IndicatorLibrary.rsi(result[price_col], 6)
        result['rsi_12'] = IndicatorLibrary.rsi(result[price_col], 12)
        result['rsi_24'] = IndicatorLibrary.rsi(result[price_col], 24)

        k, d, j = IndicatorLibrary.kdj(result['high'], result['low'], result[price_col])
        result['kdj_k'] = k
        result['kdj_d'] = d
        result['kdj_j'] = j

        result['cci'] = IndicatorLibrary.cci(result['high'], result['low'], result[price_col])
        result['williams_r'] = IndicatorLibrary.williams_r(result['high'], result['low'], result[price_col])
        result['trix'] = IndicatorLibrary.trix(result[price_col])

        pdi, mdi, adx = IndicatorLibrary.dmi(result['high'], result['low'], result[price_col])
        result['pdi'] = pdi
        result['mdi'] = mdi
        result['adx'] = adx

        # 波动指标
        result['atr'] = IndicatorLibrary.atr(result['high'], result['low'], result[price_col])

        upper, middle, lower = IndicatorLibrary.bollinger_bands(result[price_col])
        result['bb_upper'] = upper
        result['bb_middle'] = middle
        result['bb_lower'] = lower
        result['bb_width'] = (upper - lower) / middle

        # 成交量指标
        result['volume_sma_5'] = result['volume'].rolling(5).mean()
        result['volume_sma_20'] = result['volume'].rolling(20).mean()

        return result

    @staticmethod
    def get_trend_signals(df: pd.DataFrame, price_col: str = 'close') -> pd.Series:
        """
        获取趋势信号

        Args:
            df: K线数据
            price_col: 价格列名

        Returns:
            pd.Series: 信号序列 (1=多头, -1=空头, 0=无信号)
        """
        signals = pd.Series(0, index=df.index)

        if len(df) < 20:
            return signals

        # 快慢均线交叉
        fast_ma = IndicatorLibrary.sma(df[price_col], 10)
        slow_ma = IndicatorLibrary.sma(df[price_col], 30)

        # MACD
        macd, signal, _ = IndicatorLibrary.macd(df[price_col])

        # 多头信号: 快线上穿慢线 且 MACD金叉
        buy_condition = (fast_ma > slow_ma) & (macd > signal)
        signals[buy_condition] = 1

        # 空头信号: 快线下穿慢线 且 MACD死叉
        sell_condition = (fast_ma < slow_ma) & (macd < signal)
        signals[sell_condition] = -1

        return signals


def calculate_indicators(
    df: pd.DataFrame,
    indicators: Optional[List[str]] = None
) -> pd.DataFrame:
    """
    计算技术指标的便捷函数

    Args:
        df: K线数据
        indicators: 要计算的指标列表 (None=全部)

    Returns:
        pd.DataFrame: 包含指标的DataFrame
    """
    lib = IndicatorLibrary()

    if indicators is None:
        return lib.calculate_all(df)

    result = df.copy()
    for indicator in indicators:
        if indicator == 'sma':
            result['sma'] = lib.sma(result['close'], 20)
        elif indicator == 'ema':
            result['ema'] = lib.ema(result['close'], 20)
        elif indicator == 'rsi':
            result['rsi'] = lib.rsi(result['close'], 14)
        elif indicator == 'macd':
            macd, signal, hist = lib.macd(result['close'])
            result['macd'] = macd
            result['macd_signal'] = signal
            result['macd_hist'] = hist
        elif indicator == 'kdj':
            k, d, j = lib.kdj(result['high'], result['low'], result['close'])
            result['kdj_k'] = k
            result['kdj_d'] = d
            result['kdj_j'] = j
        elif indicator == 'atr':
            result['atr'] = lib.atr(result['high'], result['low'], result['close'])
        elif indicator == 'bb':
            upper, middle, lower = lib.bollinger_bands(result['close'])
            result['bb_upper'] = upper
            result['bb_middle'] = middle
            result['bb_lower'] = lower
        # 可以添加更多指标...

    return result
