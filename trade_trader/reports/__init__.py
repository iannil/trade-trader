# coding=utf-8
"""
报表生成器模块 - Report Generator Module

提供报表生成功能：
- 日报
- 周报
- 月报
- 交易分析
"""
from typing import Dict, List, Optional, Any
from decimal import Decimal
from datetime import timedelta, date
import logging
from dataclasses import dataclass, field

from django.utils import timezone
from django.db.models import Sum, Q, Avg

from panel.models import (
    Broker, Strategy, Trade, Account, Position,
    Performance,
)


logger = logging.getLogger('ReportGenerator')


@dataclass
class DailyReport:
    """日报数据"""
    date: date
    broker_name: str

    # 账户信息
    balance: Decimal
    available: Decimal
    margin: Decimal
    position_profit: Decimal
    total_asset: Decimal

    # 今日交易
    trade_count: int
    trade_volume: int
    trade_commission: Decimal

    # 今日盈亏
    close_profit: Decimal
    total_profit: Decimal

    # 持仓
    position_count: int
    long_positions: List[Dict] = field(default_factory=list)
    short_positions: List[Dict] = field(default_factory=list)

    # 按品种统计
    by_instrument: Dict[str, Dict] = field(default_factory=dict)


@dataclass
class TradeAnalysis:
    """交易分析"""
    period_start: date
    period_end: date

    # 交易统计
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float

    # 盈亏统计
    total_profit: Decimal
    total_loss: Decimal
    net_profit: Decimal
    profit_factor: float
    avg_profit: Decimal
    avg_loss: Decimal

    # 最大回撤
    max_drawdown: Decimal
    max_drawdown_pct: Decimal

    # 收益曲线
    equity_curve: List[Dict] = field(default_factory=list)


class ReportGenerator:
    """
    报表生成器

    功能：
    1. 生成日报
    2. 生成周报
    3. 生成月报
    4. 交易分析
    """

    def __init__(self, broker: Broker):
        """
        初始化报表生成器

        Args:
            broker: 券商/账户对象
        """
        self.broker = broker
        self.strategies = Strategy.objects.filter(broker=broker)

    def generate_daily_report(self, report_date: Optional[date] = None) -> DailyReport:
        """
        生成日报

        Args:
            report_date: 报告日期 (None=今日)

        Returns:
            DailyReport: 日报数据
        """
        if report_date is None:
            report_date = timezone.localtime().date()

        # 获取账户信息
        account = Account.objects.filter(broker=self.broker).first()
        if not account:
            # 如果没有Account记录，尝试从Broker获取
            account = Account(
                broker=self.broker,
                balance=self.broker.current or Decimal('0'),
                available=self.broker.cash or Decimal('0'),
                margin=self.broker.margin or Decimal('0'),
            )

        # 今日交易
        today_trades = Trade.objects.filter(
            broker=self.broker
        ).filter(
            Q(open_time__date=report_date) | Q(close_time__date=report_date)
        )

        trade_count = today_trades.count()
        trade_volume = sum([t.shares or 0 for t in today_trades])
        trade_commission = sum([t.cost or 0 for t in today_trades])

        # 今日盈亏
        close_profit = today_trades.aggregate(Sum('profit'))['profit__sum'] or Decimal('0')

        # 持仓
        positions = Position.objects.filter(
            broker=self.broker,
            position__gt=0
        )

        long_positions = []
        short_positions = []

        for pos in positions:
            pos_data = {
                'code': pos.code or pos.instrument.product_code,
                'direction': pos.direction,
                'volume': pos.position,
                'avg_price': pos.avg_open_price,
                'profit': float(pos.position_profit or 0),
            }
            if pos.direction == '0':  # LONG
                long_positions.append(pos_data)
            else:
                short_positions.append(pos_data)

        # 按品种统计
        by_instrument = {}
        for trade in today_trades:
            code = trade.code or trade.instrument.product_code
            if code not in by_instrument:
                by_instrument[code] = {
                    'volume': 0,
                    'profit': Decimal('0'),
                    'commission': Decimal('0'),
                }
            by_instrument[code]['volume'] += trade.shares or 0
            if trade.profit:
                by_instrument[code]['profit'] += trade.profit
            if trade.cost:
                by_instrument[code]['commission'] += trade.cost

        return DailyReport(
            date=report_date,
            broker_name=self.broker.name,
            balance=account.balance,
            available=account.available,
            margin=account.margin,
            position_profit=account.position_profit,
            total_asset=account.balance + account.position_profit,
            trade_count=trade_count,
            trade_volume=trade_volume,
            trade_commission=trade_commission,
            close_profit=close_profit,
            total_profit=close_profit,
            position_count=positions.count(),
            long_positions=long_positions,
            short_positions=short_positions,
            by_instrument=by_instrument
        )

    def generate_weekly_report(self, week_end: Optional[date] = None) -> Dict[str, Any]:
        """
        生成周报

        Args:
            week_end: 周结束日期 (None=本周日)

        Returns:
            Dict: 周报数据
        """
        if week_end is None:
            week_end = timezone.localtime().date()

        week_start = week_end - timedelta(days=6)

        # 本周交易
        week_trades = Trade.objects.filter(
            broker=self.broker,
            close_time__date__gte=week_start,
            close_time__date__lte=week_end,
            close_time__isnull=False
        )

        total_profit = week_trades.aggregate(Sum('profit'))['profit__sum'] or Decimal('0')

        # 按日统计
        daily_pnl = {}
        current = week_start
        while current <= week_end:
            day_pnl = Trade.objects.filter(
                broker=self.broker,
                close_time__date=current
            ).aggregate(Sum('profit'))['profit__sum'] or Decimal('0')
            daily_pnl[current.isoformat()] = float(day_pnl)
            current += timedelta(days=1)

        # 本周新开仓
        new_trades = Trade.objects.filter(
            broker=self.broker,
            open_time__date__gte=week_start,
            open_time__date__lte=week_end
        )

        # 按品种统计
        instrument_stats = {}
        for trade in week_trades:
            code = trade.code or trade.instrument.product_code
            if code not in instrument_stats:
                instrument_stats[code] = {
                    'trades': 0,
                    'volume': 0,
                    'profit': Decimal('0'),
                }
            instrument_stats[code]['trades'] += 1
            instrument_stats[code]['volume'] += trade.shares or 0
            if trade.profit:
                instrument_stats[code]['profit'] += trade.profit

        return {
            'week_start': week_start.isoformat(),
            'week_end': week_end.isoformat(),
            'total_profit': float(total_profit),
            'daily_pnl': daily_pnl,
            'trade_count': week_trades.count(),
            'new_trades': new_trades.count(),
            'instrument_stats': {
                k: {
                    'trades': v['trades'],
                    'volume': v['volume'],
                    'profit': float(v['profit'])
                }
                for k, v in instrument_stats.items()
            }
        }

    def generate_monthly_report(self, month: Optional[date] = None) -> Dict[str, Any]:
        """
        生成月报

        Args:
            month: 月份 (None=本月)

        Returns:
            Dict: 月报数据
        """
        if month is None:
            month = timezone.localtime().date()

        # 获取本月第一天和最后一天
        if isinstance(month, date):
            month_start = month.replace(day=1)
            # 获取下月第一天减一天
            if month.month == 12:
                next_month = month.replace(year=month.year + 1, month=1, day=1)
            else:
                next_month = month.replace(month=month.month + 1, day=1)
            month_end = next_month - timedelta(days=1)
        else:
            month_start = month
            month_end = month

        # 本月交易
        month_trades = Trade.objects.filter(
            broker=self.broker,
            close_time__date__gte=month_start,
            close_time__date__lte=month_end,
            close_time__isnull=False
        )

        total_profit = month_trades.aggregate(Sum('profit'))['profit__sum'] or Decimal('0')

        # 月度收益
        perf_records = Performance.objects.filter(
            broker=self.broker,
            day__gte=month_start,
            day__lte=month_end
        ).order_by('day')

        equity_curve = []
        for perf in perf_records:
            equity_curve.append({
                'date': perf.day.isoformat(),
                'nav': float(perf.NAV or 0),
                'accumulated': float(perf.accumulated or 0),
                'capital': float(perf.capital or 0),
            })

        # 统计
        total_trades = month_trades.count()
        winning_trades = month_trades.filter(profit__gt=0).count()
        losing_trades = month_trades.filter(profit__lt=0).count()
        win_rate = winning_trades / total_trades if total_trades > 0 else 0

        gross_profit = month_trades.filter(profit__gt=0).aggregate(Sum('profit'))['profit__sum'] or Decimal('0')
        gross_loss = abs(month_trades.filter(profit__lt=0).aggregate(Sum('profit'))['profit__sum'] or Decimal('0'))
        profit_factor = float(gross_profit / gross_loss) if gross_loss > 0 else 0

        return {
            'month': month_start.strftime('%Y-%m'),
            'month_start': month_start.isoformat(),
            'month_end': month_end.isoformat(),
            'total_profit': float(total_profit),
            'total_trades': total_trades,
            'winning_trades': winning_trades,
            'losing_trades': losing_trades,
            'win_rate': win_rate,
            'gross_profit': float(gross_profit),
            'gross_loss': float(gross_loss),
            'profit_factor': profit_factor,
            'equity_curve': equity_curve,
        }

    def analyze_trades(
        self,
        start_date: date,
        end_date: date
    ) -> TradeAnalysis:
        """
        分析交易

        Args:
            start_date: 开始日期
            end_date: 结束日期

        Returns:
            TradeAnalysis: 交易分析
        """
        trades = Trade.objects.filter(
            broker=self.broker,
            close_time__isnull=False,
            close_time__date__gte=start_date,
            close_time__date__lte=end_date
        )

        # 基本统计
        total_trades = trades.count()
        winning_trades = trades.filter(profit__gt=0).count()
        losing_trades = trades.filter(profit__lt=0).count()
        win_rate = winning_trades / total_trades if total_trades > 0 else 0

        # 盈亏统计
        total_profit = trades.filter(profit__gt=0).aggregate(Sum('profit'))['profit__sum'] or Decimal('0')
        total_loss = abs(trades.filter(profit__lt=0).aggregate(Sum('profit'))['profit__sum'] or Decimal('0'))
        net_profit = total_profit - total_loss

        avg_profit = trades.filter(profit__gt=0).aggregate(Avg('profit'))['profit__avg'] or Decimal('0')
        avg_loss = trades.filter(profit__lt=0).aggregate(Avg('profit'))['profit__avg'] or Decimal('0')

        profit_factor = float(total_profit / total_loss) if total_loss > 0 else 0

        # 收益曲线
        equity_curve = []
        cumulative_pnl = Decimal('0')

        # 按日期分组
        daily_pnl = {}
        for trade in trades.order_by('close_time'):
            close_date = trade.close_time.date()
            if close_date not in daily_pnl:
                daily_pnl[close_date] = Decimal('0')
            if trade.profit:
                daily_pnl[close_date] += trade.profit

        for date_key, pnl in sorted(daily_pnl.items()):
            cumulative_pnl += pnl
            equity_curve.append({
                'date': date_key.isoformat(),
                'equity': float(cumulative_pnl)
            })

        # 最大回撤
        max_dd = self._calculate_max_drawdown_from_curve(equity_curve)

        return TradeAnalysis(
            period_start=start_date,
            period_end=end_date,
            total_trades=total_trades,
            winning_trades=winning_trades,
            losing_trades=losing_trades,
            win_rate=win_rate,
            total_profit=total_profit,
            total_loss=total_loss,
            net_profit=net_profit,
            profit_factor=profit_factor,
            avg_profit=avg_profit,
            avg_loss=avg_loss,
            max_drawdown=max_dd['amount'],
            max_drawdown_pct=max_dd['pct'],
            equity_curve=equity_curve
        )

    def _calculate_max_drawdown_from_curve(self, equity_curve: List[Dict]) -> Dict:
        """从权益曲线计算最大回撤"""
        if not equity_curve:
            return {'amount': 0, 'pct': 0}

        max_equity = 0
        max_dd = 0
        max_dd_pct = 0

        for point in equity_curve:
            equity = point['equity']
            if equity > max_equity:
                max_equity = equity

            drawdown = max_equity - equity
            if drawdown > max_dd:
                max_dd = drawdown

            if max_equity > 0:
                dd_pct = drawdown / max_equity
                if dd_pct > max_dd_pct:
                    max_dd_pct = dd_pct

        return {'amount': max_dd, 'pct': max_dd_pct}

    def format_daily_report_text(self, report: DailyReport) -> str:
        """
        格式化日报文本

        Args:
            report: 日报数据

        Returns:
            str: 格式化的日报文本
        """
        lines = [
            "=" * 50,
            f"交易日报 - {report.date}",
            f"账户: {report.broker_name}",
            "=" * 50,
            "",
            "【账户概览】",
            f"  静态权益: {report.balance:,.2f}",
            f"  可用资金: {report.available:,.2f}",
            f"  占用保证金: {report.margin:,.2f}",
            f"  持仓盈亏: {report.position_profit:,.2f}",
            f"  总资产: {report.total_asset:,.2f}",
            "",
            "【今日交易】",
            f"  交易次数: {report.trade_count}",
            f"  成交手数: {report.trade_volume}",
            f"  手续费: {report.trade_commission:,.2f}",
            f"  平仓盈亏: {report.close_profit:,.2f}",
            "",
            "【当前持仓】",
            f"  持仓数量: {report.position_count}",
        ]

        if report.long_positions:
            lines.append("  多头持仓:")
            for pos in report.long_positions:
                code = pos.get('code', '')
                volume = pos.get('volume', 0)
                avg_price = pos.get('avg_price', 0)
                lines.append(f"    {code}: {volume}手 @{avg_price}")

        if report.short_positions:
            lines.append("  空头持仓:")
            for pos in report.short_positions:
                code = pos.get('code', '')
                volume = pos.get('volume', 0)
                avg_price = pos.get('avg_price', 0)
                lines.append(f"    {code}: {volume}手 @{avg_price}")

        lines.extend([
            "",
            "【按品种统计】"
        ])

        for code, stats in report.by_instrument.items():
            lines.append(
                f"  {code}: {stats['volume']}手 "
                f"盈亏:{stats['profit']:,.2f}"
            )

        lines.append("=" * 50)

        return "\n".join(lines)

    def format_html_report(self, report_data: Dict, report_type: str = "daily") -> str:
        """
        格式化HTML报表

        Args:
            report_data: 报表数据
            report_type: 报表类型 (daily, weekly, monthly)

        Returns:
            str: HTML格式的报表
        """
        if report_type == "daily":
            return self._format_daily_html(report_data)
        elif report_type == "weekly":
            return self._format_weekly_html(report_data)
        elif report_type == "monthly":
            return self._format_monthly_html(report_data)
        else:
            return "<p>Unknown report type</p>"

    def _format_daily_html(self, report: DailyReport) -> str:
        """格式化日报HTML"""
        html = f"""
        <html>
        <head>
            <title>交易日报 {report.date}</title>
            <style>
                body {{ font-family: Arial, sans-serif; margin: 20px; }}
                table {{ border-collapse: collapse; width: 100%; margin: 20px 0; }}
                th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
                th {{ background-color: #f2f2f2; }}
                .positive {{ color: green; }}
                .negative {{ color: red; }}
                .section {{ margin: 30px 0; }}
                h1 {{ color: #333; }}
                h2 {{ color: #666; }}
            </style>
        </head>
        <body>
            <h1>交易日报 - {report.date}</h1>
            <p>账户: {report.broker_name}</p>

            <div class="section">
                <h2>账户概览</h2>
                <table>
                    <tr><th>项目</th><th>值</th></tr>
                    <tr><td>静态权益</td><td>{report.balance:,.2f}</td></tr>
                    <tr><td>可用资金</td><td>{report.available:,.2f}</td></tr>
                    <tr><td>占用保证金</td><td>{report.margin:,.2f}</td></tr>
                    <tr><td>持仓盈亏</td><td class="{'positive' if report.position_profit >= 0 else 'negative'}">{report.position_profit:,.2f}</td></tr>
                    <tr><td>总资产</td><td>{report.total_asset:,.2f}</td></tr>
                </table>
            </div>

            <div class="section">
                <h2>今日交易</h2>
                <table>
                    <tr><th>项目</th><th>值</th></tr>
                    <tr><td>交易次数</td><td>{report.trade_count}</td></tr>
                    <tr><td>成交手数</td><td>{report.trade_volume}</td></tr>
                    <tr><td>手续费</td><td>{report.trade_commission:,.2f}</td></tr>
                    <tr><td>平仓盈亏</td><td class="{'positive' if report.close_profit >= 0 else 'negative'}">{report.close_profit:,.2f}</td></tr>
                </table>
            </div>

            <div class="section">
                <h2>当前持仓</h2>
                <table>
                    <tr><th>合约</th><th>方向</th><th>手数</th><th>均价</th><th>浮动盈亏</th></tr>
        """

        for pos in report.long_positions:
            html += f"""
                    <tr>
                        <td>{pos['code']}</td>
                        <td>多</td>
                        <td>{pos['volume']}</td>
                        <td>{pos['avg_price']}</td>
                        <td class="{'positive' if pos['profit'] >= 0 else 'negative'}">{pos['profit']:,.2f}</td>
                    </tr>
            """

        for pos in report.short_positions:
            html += f"""
                    <tr>
                        <td>{pos['code']}</td>
                        <td>空</td>
                        <td>{pos['volume']}</td>
                        <td>{pos['avg_price']}</td>
                        <td class="{'positive' if pos['profit'] >= 0 else 'negative'}">{pos['profit']:,.2f}</td>
                    </tr>
            """

        html += """
                </table>
            </div>
        </body>
        </html>
        """

        return html


def create_report_generator(broker: Broker) -> ReportGenerator:
    """创建报表生成器"""
    return ReportGenerator(broker)
