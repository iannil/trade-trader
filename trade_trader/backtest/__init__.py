# coding=utf-8
"""
回测引擎模块 - Backtesting Engine Module

提供完整的策略回测功能：
- BacktestEngine: 回测引擎主类
- 加载历史数据
- 运行回测
- 计算绩效指标
"""
from typing import Optional, Dict, List, Callable, Tuple
from decimal import Decimal
import datetime
import logging
from dataclasses import dataclass, field

import pandas as pd
from django.utils import timezone

from panel.models import (
    Instrument, MainBar, Strategy,
    DirectionType, SignalType
)
from trade_trader.backtest.metrics import PerformanceMetrics


logger = logging.getLogger('BacktestEngine')


@dataclass
class BacktestConfig:
    """回测配置"""
    start_date: datetime.date
    end_date: datetime.date
    initial_capital: Decimal = Decimal('1000000')  # 初始资金
    commission_rate: Decimal = Decimal('0.0001')    # 手续费率
    slippage: Decimal = Decimal('0.0001')           # 滑点
    position_size: Decimal = Decimal('1')           # 默认持仓手数
    margin_rate: Decimal = Decimal('0.15')          # 保证金比例


@dataclass
class TradeRecord:
    """交易记录"""
    code: str
    instrument: str
    direction: DirectionType
    entry_time: datetime.datetime
    exit_time: Optional[datetime.datetime]
    entry_price: Decimal
    exit_price: Optional[Decimal]
    volume: int
    profit: Optional[Decimal]
    profit_pct: Optional[Decimal]
    exit_reason: str = ""


@dataclass
class BacktestResult:
    """回测结果"""
    config: BacktestConfig

    # 基本信息
    strategy_name: str
    start_date: datetime.date
    end_date: datetime.date

    # 交易统计
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate: Decimal = Decimal('0')

    # 收益统计
    total_return: Decimal = Decimal('0')
    annual_return: Decimal = Decimal('0')
    max_drawdown: Decimal = Decimal('0')
    max_drawdown_pct: Decimal = Decimal('0')

    # 盈亏统计
    gross_profit: Decimal = Decimal('0')
    gross_loss: Decimal = Decimal('0')
    net_profit: Decimal = Decimal('0')
    avg_profit: Decimal = Decimal('0')
    avg_loss: Decimal = Decimal('0')
    profit_factor: Decimal = Decimal('0')

    # 风险指标
    sharpe_ratio: Decimal = Decimal('0')
    sortino_ratio: Decimal = Decimal('0')
    calmar_ratio: Decimal = Decimal('0')

    # 交易记录
    trades: List[TradeRecord] = field(default_factory=list)

    # 权益曲线
    equity_curve: pd.Series = field(default_factory=pd.Series)

    def to_dict(self) -> Dict:
        """转换为字典"""
        return {
            'strategy_name': self.strategy_name,
            'start_date': self.start_date,
            'end_date': self.end_date,
            'total_trades': self.total_trades,
            'winning_trades': self.winning_trades,
            'losing_trades': self.losing_trades,
            'win_rate': float(self.win_rate),
            'total_return': float(self.total_return),
            'annual_return': float(self.annual_return),
            'max_drawdown': float(self.max_drawdown),
            'max_drawdown_pct': float(self.max_drawdown_pct),
            'gross_profit': float(self.gross_profit),
            'gross_loss': float(self.gross_loss),
            'net_profit': float(self.net_profit),
            'avg_profit': float(self.avg_profit),
            'avg_loss': float(self.avg_loss),
            'profit_factor': float(self.profit_factor),
            'sharpe_ratio': float(self.sharpe_ratio),
            'sortino_ratio': float(self.sortino_ratio),
            'calmar_ratio': float(self.calmar_ratio),
        }


class BacktestEngine:
    """
    回测引擎

    功能：
    1. 加载历史数据
    2. 运行回测
    3. 计算绩效指标
    4. 生成报告
    """

    def __init__(self, strategy: Strategy, config: Optional[BacktestConfig] = None):
        """
        初始化回测引擎

        Args:
            strategy: 策略对象
            config: 回测配置
        """
        self.strategy = strategy
        self.config = config or BacktestConfig(
            start_date=timezone.localtime().date() - datetime.timedelta(days=365),
            end_date=timezone.localtime().date()
        )
        self.instruments = list(strategy.instruments.all())
        self.metrics_calculator = PerformanceMetrics()

    def load_history(self, instrument: Instrument) -> pd.DataFrame:
        """
        加载历史数据

        Args:
            instrument: 合约对象

        Returns:
            pd.DataFrame: 历史K线数据
        """
        bars = MainBar.objects.filter(
            exchange=instrument.exchange,
            product_code=instrument.product_code,
            time__gte=self.config.start_date,
            time__lte=self.config.end_date
        ).order_by('time').values_list(
            'time', 'open', 'high', 'low', 'close', 'settlement', 'volume', 'open_interest'
        )

        if not bars:
            logger.warning(f"未找到 {instrument.product_code} 的历史数据")
            return pd.DataFrame()

        df = pd.DataFrame(list(bars), columns=[
            'time', 'open', 'high', 'low', 'close', 'settlement', 'volume', 'open_interest'
        ])
        df.set_index('time', inplace=True)

        # 转换数据类型
        for col in ['open', 'high', 'low', 'close', 'settlement']:
            df[col] = df[col].astype(float)
        df['volume'] = df['volume'].astype(int)

        return df

    def load_all_history(self) -> Dict[str, pd.DataFrame]:
        """
        加载所有合约的历史数据

        Returns:
            Dict[str, pd.DataFrame]: {product_code: DataFrame}
        """
        data = {}
        for inst in self.instruments:
            df = self.load_history(inst)
            if not df.empty:
                data[inst.product_code] = df
        return data

    def run_backtest(
        self,
        signal_generator: Callable[[pd.DataFrame, Instrument], List[Dict]],
        progress_callback: Optional[Callable] = None
    ) -> BacktestResult:
        """
        运行回测

        Args:
            signal_generator: 信号生成器函数
                参数: (df: DataFrame, instrument: Instrument)
                返回: 信号列表 [{'type': SignalType, 'time': datetime, 'price': Decimal, 'volume': int}, ...]
            progress_callback: 进度回调函数

        Returns:
            BacktestResult: 回测结果
        """
        logger.info(f"开始回测: {self.strategy.name} "
                   f"从 {self.config.start_date} 到 {self.config.end_date}")

        # 加载历史数据
        historical_data = self.load_all_history()
        if not historical_data:
            logger.error("没有可用的历史数据")
            return self._empty_result()

        # 初始化回测状态
        capital = self.config.initial_capital
        position = {}  # {code: {'direction': DirectionType, 'volume': int, 'entry_price': Decimal, 'entry_time': datetime}}
        trades = []
        equity_curve = []

        # 合并所有数据的时间索引
        all_dates = set()
        for df in historical_data.values():
            all_dates.update(df.index)
        date_range = sorted(all_dates)

        # 按日期遍历
        for i, current_date in enumerate(date_range):
            # 更新权益
            current_equity = self._calculate_equity(capital, position, historical_data, current_date)
            equity_curve.append({'date': current_date, 'equity': float(current_equity)})

            # 为每个合约生成信号
            for inst in self.instruments:
                product_code = inst.product_code
                if product_code not in historical_data:
                    continue

                df = historical_data[product_code]
                if current_date not in df.index:
                    continue

                # 获取当前日期之前的数据
                historical_df = df[df.index <= current_date].copy()

                # 生成信号
                try:
                    signals = signal_generator(historical_df, inst)
                except Exception as e:
                    logger.warning(f"信号生成错误 {inst.product_code}: {repr(e)}")
                    continue

                # 处理信号
                for sig in signals:
                    trade_record = self._process_signal(sig, inst, position, capital, current_date)
                    if trade_record:
                        trades.append(trade_record)

            # 进度回调
            if progress_callback:
                progress = (i + 1) / len(date_range) * 100
                progress_callback(progress)

        # 计算回测结果
        result = self._calculate_result(trades, equity_curve, capital)
        logger.info(f"回测完成: 总收益 {result.total_return:.2%}, 夏普比率 {result.sharpe_ratio:.2f}")

        return result

    def run_vectorized_backtest(
        self,
        signals_df: pd.DataFrame
    ) -> BacktestResult:
        """
        运行向量化回测

        Args:
            signals_df: 信号数据框
                必须包含列: date, code, signal, price
                signal: 1=买入, -1=卖出

        Returns:
            BacktestResult: 回测结果
        """
        if signals_df.empty:
            return self._empty_result()

        # 按日期排序
        signals_df = signals_df.sort_values('date').reset_index(drop=True)

        # 初始化
        capital = self.config.initial_capital
        position = 0  # 持仓量 (正数为多头，负数为空头)
        entry_price = None
        trades = []
        equity_values = []

        for _, row in signals_df.iterrows():
            date = row['date']
            signal = row['signal']
            price = Decimal(str(row['price']))

            # 计算当前权益
            if position != 0 and entry_price:
                pnl = (price - entry_price) * position
                current_equity = capital + pnl
            else:
                current_equity = capital
            equity_values.append({'date': date, 'equity': float(current_equity)})

            # 处理信号
            if signal == 1 and position <= 0:  # 买入信号
                if position < 0:  # 先平空头
                    profit = (entry_price - price) * abs(position)
                    capital += profit
                    trades.append(self._create_trade_record(
                        code=row.get('code', ''),
                        direction=DirectionType.SHORT,
                        entry_price=entry_price,
                        exit_price=price,
                        volume=abs(position),
                        profit=profit
                    ))
                # 开多头
                position = int(capital / price)
                entry_price = price
                capital -= position * price

            elif signal == -1 and position >= 0:  # 卖出信号
                if position > 0:  # 先平多头
                    profit = (price - entry_price) * position
                    capital += profit
                    trades.append(self._create_trade_record(
                        code=row.get('code', ''),
                        direction=DirectionType.LONG,
                        entry_price=entry_price,
                        exit_price=price,
                        volume=position,
                        profit=profit
                    ))
                # 开空头
                position = -int(capital / price)
                entry_price = price
                capital += abs(position) * price

        # 平仓剩余持仓
        if position != 0 and entry_price:
            last_price = Decimal(str(signals_df.iloc[-1]['price']))
            if position > 0:
                profit = (last_price - entry_price) * position
            else:
                profit = (entry_price - last_price) * abs(position)
            capital += profit
            trades.append(self._create_trade_record(
                code=signals_df.iloc[-1].get('code', ''),
                direction=DirectionType.LONG if position > 0 else DirectionType.SHORT,
                entry_price=entry_price,
                exit_price=last_price,
                volume=abs(position),
                profit=profit
            ))

        return self._calculate_result(trades, equity_values, capital)

    def _process_signal(
        self,
        signal: Dict,
        instrument: Instrument,
        position: Dict,
        capital: Decimal,
        current_date: datetime.date
    ) -> Optional[TradeRecord]:
        """处理交易信号"""
        sig_type = signal.get('type')
        price = Decimal(str(signal.get('price', 0)))
        volume = int(signal.get('volume', self.config.position_size))
        sig_time = signal.get('time', current_date)

        main_code = instrument.main_code or signal.get('code', instrument.product_code)

        if sig_type in [SignalType.BUY, SignalType.SELL_SHORT]:
            # 开仓
            direction = DirectionType.LONG if sig_type == SignalType.BUY else DirectionType.SHORT

            # 计算所需保证金
            margin = price * volume * instrument.volume_multiple * self.config.margin_rate

            if margin > capital:
                logger.warning(f"资金不足，无法开仓: {instrument.product_code}")
                return None

            # 更新持仓
            position[main_code] = {
                'direction': direction,
                'volume': volume,
                'entry_price': price,
                'entry_time': sig_time,
            }
            capital -= margin

        elif sig_type in [SignalType.SELL, SignalType.BUY_COVER]:
            # 平仓
            if main_code not in position:
                return None

            pos = position[main_code]
            exit_direction = DirectionType.SHORT if sig_type == SignalType.SELL else DirectionType.LONG

            if pos['direction'] != exit_direction:
                return None

            # 计算盈亏
            if pos['direction'] == DirectionType.LONG:
                profit = (price - pos['entry_price']) * volume * instrument.volume_multiple
            else:
                profit = (pos['entry_price'] - price) * volume * instrument.volume_multiple

            # 扣除手续费
            commission = price * volume * instrument.volume_multiple * self.config.commission_rate
            profit -= commission

            capital += profit + (pos['entry_price'] * volume * instrument.volume_multiple * self.config.margin_rate)

            # 创建交易记录
            trade_record = TradeRecord(
                code=main_code,
                instrument=instrument.product_code,
                direction=pos['direction'],
                entry_time=pos['entry_time'],
                exit_time=sig_time,
                entry_price=pos['entry_price'],
                exit_price=price,
                volume=volume,
                profit=profit,
                profit_pct=profit / (pos['entry_price'] * volume * instrument.volume_multiple) if volume > 0 else Decimal('0'),
                exit_reason='signal'
            )

            del position[main_code]
            return trade_record

        return None

    def _calculate_equity(
        self,
        capital: Decimal,
        position: Dict,
        historical_data: Dict[str, pd.DataFrame],
        current_date: datetime.date
    ) -> Decimal:
        """计算当前权益"""
        equity = capital

        for code, pos in position.items():
            # 获取当前价格
            instrument_code = None
            for inst in self.instruments:
                if inst.main_code == code or inst.product_code == code:
                    instrument_code = inst.product_code
                    break

            if instrument_code and instrument_code in historical_data:
                df = historical_data[instrument_code]
                if current_date in df.index:
                    current_price = Decimal(str(df.loc[current_date, 'close']))
                    if pos['direction'] == DirectionType.LONG:
                        unrealized_pnl = (current_price - pos['entry_price']) * pos['volume']
                    else:
                        unrealized_pnl = (pos['entry_price'] - current_price) * pos['volume']
                    equity += unrealized_pnl

        return equity

    def _create_trade_record(
        self,
        code: str,
        direction: DirectionType,
        entry_price: Decimal,
        exit_price: Decimal,
        volume: int,
        profit: Decimal
    ) -> TradeRecord:
        """创建交易记录"""
        profit_pct = profit / (entry_price * volume) if volume > 0 and entry_price > 0 else Decimal('0')
        return TradeRecord(
            code=code,
            instrument=code,
            direction=direction,
            entry_time=datetime.datetime.now(),
            exit_time=datetime.datetime.now(),
            entry_price=entry_price,
            exit_price=exit_price,
            volume=volume,
            profit=profit,
            profit_pct=profit_pct
        )

    def _calculate_result(
        self,
        trades: List[TradeRecord],
        equity_curve: List[Dict],
        final_capital: Decimal
    ) -> BacktestResult:
        """计算回测结果"""
        result = BacktestResult(
            config=self.config,
            strategy_name=self.strategy.name,
            start_date=self.config.start_date,
            end_date=self.config.end_date,
            trades=trades,
            equity_curve=pd.DataFrame(equity_curve).set_index('date')['equity'] if equity_curve else pd.Series()
        )

        if not trades:
            return result

        # 基本统计
        result.total_trades = len(trades)
        result.winning_trades = sum(1 for t in trades if t.profit and t.profit > 0)
        result.losing_trades = sum(1 for t in trades if t.profit and t.profit < 0)
        result.win_rate = Decimal(result.winning_trades / result.total_trades) if result.total_trades > 0 else Decimal('0')

        # 盈亏统计
        profits = [t.profit for t in trades if t.profit and t.profit > 0]
        losses = [abs(t.profit) for t in trades if t.profit and t.profit < 0]

        result.gross_profit = Decimal(sum(profits)) if profits else Decimal('0')
        result.gross_loss = Decimal(sum(losses)) if losses else Decimal('0')
        result.net_profit = result.gross_profit - result.gross_loss
        result.avg_profit = Decimal(result.gross_profit / len(profits)) if profits else Decimal('0')
        result.avg_loss = Decimal(result.gross_loss / len(losses)) if losses else Decimal('0')
        result.profit_factor = result.gross_profit / result.gross_loss if result.gross_loss > 0 else Decimal('0')

        # 收益统计
        result.total_return = (final_capital - self.config.initial_capital) / self.config.initial_capital

        # 年化收益率
        days = (self.config.end_date - self.config.start_date).days
        if days > 0:
            result.annual_return = (Decimal('1') + result.total_return) ** (Decimal('365') / Decimal(days)) - Decimal('1')

        # 最大回撤
        if not result.equity_curve.empty:
            result.max_drawdown, result.max_drawdown_pct = self._calculate_max_drawdown(result.equity_curve)

        # 夏普比率
        if not result.equity_curve.empty:
            result.sharpe_ratio = self.metrics_calculator.sharpe_ratio(result.equity_curve)
            result.sortino_ratio = self.metrics_calculator.sortino_ratio(result.equity_curve)
            result.calmar_ratio = abs(result.annual_return / result.max_drawdown_pct) if result.max_drawdown_pct != 0 else Decimal('0')

        return result

    def _calculate_max_drawdown(self, equity_curve: pd.Series) -> Tuple[Decimal, Decimal]:
        """计算最大回撤"""
        if equity_curve.empty:
            return Decimal('0'), Decimal('0')

        running_max = equity_curve.expanding().max()
        drawdown = (equity_curve - running_max) / running_max
        max_dd_pct = Decimal(str(drawdown.min()))
        max_dd = Decimal(str(drawdown.min() * equity_curve.iloc[0]))  # 粗略估计

        return max_dd, max_dd_pct

    def _empty_result(self) -> BacktestResult:
        """返回空结果"""
        return BacktestResult(
            config=self.config,
            strategy_name=self.strategy.name,
            start_date=self.config.start_date,
            end_date=self.config.end_date,
            equity_curve=pd.Series(dtype=float)
        )


def create_backtest_engine(strategy: Strategy, config: Optional[BacktestConfig] = None) -> BacktestEngine:
    """
    创建回测引擎的工厂函数

    Args:
        strategy: 策略对象
        config: 回测配置

    Returns:
        BacktestEngine: 回测引擎实例
    """
    return BacktestEngine(strategy, config)
