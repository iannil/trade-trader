# coding=utf-8
"""
参数优化模块 - Parameter Optimization Module

提供策略参数优化功能：
- 网格搜索
- 遗传算法
- 步进检验
"""
from typing import Dict, List, Callable, Optional, Any, Tuple
from decimal import Decimal
import logging
from dataclasses import dataclass
from itertools import product
import datetime

import numpy as np
import pandas as pd

from trade_trader.backtest import BacktestEngine, BacktestConfig, BacktestResult
from panel.models import Strategy, MainBar


logger = logging.getLogger('ParameterOptimizer')


@dataclass
class OptimizationResult:
    """优化结果"""
    params: Dict[str, Any]
    metrics: Dict[str, float]
    equity_curve: pd.Series
    trades: List


@dataclass
class OptimizationReport:
    """优化报告"""
    best_result: OptimizationResult
    all_results: List[OptimizationResult]
    total_iterations: int
    computation_time: float

    def to_dataframe(self) -> pd.DataFrame:
        """将所有结果转换为DataFrame"""
        data = []
        for result in self.all_results:
            row = result.params.copy()
            row.update(result.metrics)
            data.append(row)
        return pd.DataFrame(data)

    def get_top_n(self, n: int = 10) -> List[OptimizationResult]:
        """获取前N个结果"""
        return sorted(self.all_results, key=lambda x: x.metrics.get('sharpe_ratio', 0), reverse=True)[:n]


class ParameterOptimizer:
    """
    参数优化器

    功能：
    1. 网格搜索 (Grid Search)
    2. 遗传算法 (Genetic Algorithm)
    3. 步进检验 (Walk Forward Test)
    """

    def __init__(self, strategy: Strategy, config: Optional[BacktestConfig] = None):
        """
        初始化参数优化器

        Args:
            strategy: 策略对象
            config: 回测配置
        """
        self.strategy = strategy
        self.config = config
        self.results: List[OptimizationResult] = []

    def grid_search(
        self,
        param_grid: Dict[str, List],
        signal_generator: Callable,
        metric: str = 'sharpe_ratio',
        progress_callback: Optional[Callable] = None
    ) -> OptimizationReport:
        """
        网格搜索参数优化

        Args:
            param_grid: 参数网格
                例如: {'break_period': [20, 30, 40], 'atr_period': [10, 14, 20]}
            signal_generator: 信号生成器函数
                函数签名: (df: pd.DataFrame, instrument: Instrument, params: dict) -> List[Dict]
            metric: 优化目标指标 ('sharpe_ratio', 'total_return', 'calmar_ratio', 'profit_factor')
            progress_callback: 进度回调函数

        Returns:
            OptimizationReport: 优化报告
        """
        logger.info(f"开始网格搜索优化: {list(param_grid.keys())}")

        start_time = datetime.datetime.now()
        all_results = []

        # 生成所有参数组合
        param_names = list(param_grid.keys())
        param_values = list(param_grid.values())
        all_combinations = list(product(*param_values))

        total_iterations = len(all_combinations)
        logger.info(f"总共 {total_iterations} 个参数组合")

        for i, combination in enumerate(all_combinations):
            # 构建参数字典
            params = dict(zip(param_names, combination))

            # 运行回测
            engine = BacktestEngine(self.strategy, self.config)
            result = self._run_with_params(engine, signal_generator, params)

            if result:
                opt_result = OptimizationResult(
                    params=params,
                    metrics=result.to_dict(),
                    equity_curve=result.equity_curve,
                    trades=result.trades
                )
                all_results.append(opt_result)

            # 进度回调
            if progress_callback:
                progress = (i + 1) / total_iterations * 100
                progress_callback(progress, params, result)

        # 选择最佳结果
        best_result = self._select_best(all_results, metric)

        computation_time = (datetime.datetime.now() - start_time).total_seconds()

        logger.info(f"网格搜索完成: 最佳参数={best_result.params}, {metric}={best_result.metrics.get(metric, 0):.4f}")

        return OptimizationReport(
            best_result=best_result,
            all_results=all_results,
            total_iterations=total_iterations,
            computation_time=computation_time
        )

    def random_search(
        self,
        param_ranges: Dict[str, Tuple],
        n_iter: int = 100,
        signal_generator: Callable = None,
        metric: str = 'sharpe_ratio',
        progress_callback: Optional[Callable] = None
    ) -> OptimizationReport:
        """
        随机搜索参数优化

        Args:
            param_ranges: 参数范围
                例如: {'break_period': (10, 50), 'atr_period': (5, 30)}
                支持连续值范围和离散值列表
            n_iter: 迭代次数
            signal_generator: 信号生成器函数
            metric: 优化目标指标
            progress_callback: 进度回调函数

        Returns:
            OptimizationReport: 优化报告
        """
        logger.info(f"开始随机搜索优化: {n_iter} 次迭代")

        start_time = datetime.datetime.now()
        all_results = []

        for i in range(n_iter):
            # 随机生成参数
            params = {}
            for name, value_range in param_ranges.items():
                if isinstance(value_range, tuple) and len(value_range) == 2:
                    # 连续值范围
                    if isinstance(value_range[0], int):
                        params[name] = np.random.randint(value_range[0], value_range[1] + 1)
                    else:
                        params[name] = np.random.uniform(value_range[0], value_range[1])
                elif isinstance(value_range, list):
                    # 离散值列表
                    params[name] = np.random.choice(value_range)
                else:
                    params[name] = value_range

            # 运行回测
            engine = BacktestEngine(self.strategy, self.config)
            result = self._run_with_params(engine, signal_generator, params)

            if result:
                opt_result = OptimizationResult(
                    params=params,
                    metrics=result.to_dict(),
                    equity_curve=result.equity_curve,
                    trades=result.trades
                )
                all_results.append(opt_result)

            # 进度回调
            if progress_callback:
                progress = (i + 1) / n_iter * 100
                progress_callback(progress, params, result)

        # 选择最佳结果
        best_result = self._select_best(all_results, metric)

        computation_time = (datetime.datetime.now() - start_time).total_seconds()

        logger.info(f"随机搜索完成: 最佳参数={best_result.params}, {metric}={best_result.metrics.get(metric, 0):.4f}")

        return OptimizationReport(
            best_result=best_result,
            all_results=all_results,
            total_iterations=n_iter,
            computation_time=computation_time
        )

    def walk_forward_test(
        self,
        param_grid: Dict[str, List],
        signal_generator: Callable,
        train_size: int = 252,  # 训练期约1年
        test_size: int = 63,    # 测试期约3个月
        step_size: int = 21,    # 步进约1个月
        metric: str = 'sharpe_ratio',
        progress_callback: Optional[Callable] = None
    ) -> OptimizationReport:
        """
        步进检验 (Walk Forward Test)

        Args:
            param_grid: 参数网格
            signal_generator: 信号生成器函数
            train_size: 训练期长度 (天)
            test_size: 测试期长度 (天)
            step_size: 步进长度 (天)
            metric: 优化目标指标
            progress_callback: 进度回调函数

        Returns:
            OptimizationReport: 优化报告
        """
        logger.info(f"开始步进检验优化: 训练期={train_size}天, 测试期={test_size}天, 步进={step_size}天")

        start_time = datetime.datetime.now()
        all_results = []

        # 获取数据日期范围
        instruments = list(self.strategy.instruments.all())
        if not instruments:
            logger.error("策略没有配置交易品种")
            return self._empty_report()

        # 获取日期范围
        all_dates = MainBar.objects.filter(
            exchange=instruments[0].exchange,
            product_code=instruments[0].product_code
        ).order_by('time').values_list('time', flat=True)

        if not all_dates:
            logger.error("没有历史数据")
            return self._empty_report()

        all_dates = sorted(set(all_dates))

        # 步进检验
        fold = 0
        current_idx = 0

        while current_idx + train_size + test_size <= len(all_dates):
            fold += 1
            train_start = all_dates[current_idx]
            train_end = all_dates[current_idx + train_size - 1]
            test_start = all_dates[current_idx + train_size]
            test_end = all_dates[current_idx + train_size + test_size - 1]

            logger.info(f"Fold {fold}: 训练期 {train_start} - {train_end}, 测试期 {test_start} - {test_end}")

            # 训练期优化参数
            # TODO: train_engine and train_config are created but not used - implement training phase
            # train_config = BacktestConfig(
            #     start_date=train_start,
            #     end_date=train_end,
            #     initial_capital=self.config.initial_capital if self.config else Decimal('1000000')
            # )
            # train_engine = BacktestEngine(self.strategy, train_config)
            train_report = self.grid_search(param_grid, signal_generator, metric, None)
            best_params = train_report.best_result.params

            # 测试期验证
            test_config = BacktestConfig(
                start_date=test_start,
                end_date=test_end,
                initial_capital=self.config.initial_capital if self.config else Decimal('1000000')
            )

            test_engine = BacktestEngine(self.strategy, test_config)
            test_result = self._run_with_params(test_engine, signal_generator, best_params)

            if test_result:
                opt_result = OptimizationResult(
                    params=best_params,
                    metrics=test_result.to_dict(),
                    equity_curve=test_result.equity_curve,
                    trades=test_result.trades
                )
                opt_result.params['_fold'] = fold
                opt_result.params['_train_start'] = train_start
                opt_result.params['_train_end'] = train_end
                opt_result.params['_test_start'] = test_start
                opt_result.params['_test_end'] = test_end
                all_results.append(opt_result)

            # 进度回调
            if progress_callback:
                progress = (fold * step_size) / (len(all_dates) - train_size) * 100
                progress_callback(progress, best_params, test_result)

            current_idx += step_size

        # 计算平均性能
        if all_results:
            best_result = self._average_results(all_results)
        else:
            best_result = OptimizationResult(
                params={},
                metrics={},
                equity_curve=pd.Series(),
                trades=[]
            )

        computation_time = (datetime.datetime.now() - start_time).total_seconds()

        logger.info(f"步进检验完成: {fold} 折交叉验证")

        return OptimizationReport(
            best_result=best_result,
            all_results=all_results,
            total_iterations=fold,
            computation_time=computation_time
        )

    def _run_with_params(
        self,
        engine: BacktestEngine,
        signal_generator: Callable,
        params: Dict[str, Any]
    ) -> Optional[BacktestResult]:
        """
        使用指定参数运行回测

        Args:
            engine: 回测引擎
            signal_generator: 信号生成器
            params: 参数字典

        Returns:
            BacktestResult: 回测结果
        """
        try:
            # 创建带参数的信号生成器
            def param_signal_generator(df, instrument):
                return signal_generator(df, instrument, params)

            result = engine.run_backtest(param_signal_generator, None)
            return result
        except Exception as e:
            logger.warning(f"回测失败 (params={params}): {repr(e)}")
            return None

    def _select_best(
        self,
        results: List[OptimizationResult],
        metric: str
    ) -> OptimizationResult:
        """选择最佳结果"""
        if not results:
            return OptimizationResult(
                params={},
                metrics={},
                equity_curve=pd.Series(),
                trades=[]
            )

        return max(results, key=lambda x: x.metrics.get(metric, -float('inf')))

    def _average_results(self, results: List[OptimizationResult]) -> OptimizationResult:
        """计算平均结果"""
        if not results:
            return OptimizationResult(
                params={},
                metrics={},
                equity_curve=pd.Series(),
                trades=[]
            )

        # 合并权益曲线
        all_equity = []
        for r in results:
            if not r.equity_curve.empty:
                normalized = r.equity_curve / r.equity_curve.iloc[0] if r.equity_curve.iloc[0] > 0 else r.equity_curve
                all_equity.append(normalized)

        if all_equity:
            # 简化处理：取平均值
            avg_equity = pd.concat(all_equity, axis=1).mean(axis=1)
        else:
            avg_equity = pd.Series()

        # 平均指标
        avg_metrics = {}
        metric_keys = results[0].metrics.keys()
        for key in metric_keys:
            values = [r.metrics.get(key, 0) for r in results if key in r.metrics]
            if values:
                avg_metrics[key] = np.mean(values)

        return OptimizationResult(
            params={},  # 平均结果没有单一参数集
            metrics=avg_metrics,
            equity_curve=avg_equity,
            trades=[]
        )

    def _empty_report(self) -> OptimizationReport:
        """返回空报告"""
        return OptimizationReport(
            best_result=OptimizationResult(
                params={},
                metrics={},
                equity_curve=pd.Series(),
                trades=[]
            ),
            all_results=[],
            total_iterations=0,
            computation_time=0.0
        )


def create_optimizer(strategy: Strategy, config: Optional[BacktestConfig] = None) -> ParameterOptimizer:
    """
    创建参数优化器的工厂函数

    Args:
        strategy: 策略对象
        config: 回测配置

    Returns:
        ParameterOptimizer: 参数优化器实例
    """
    return ParameterOptimizer(strategy, config)
