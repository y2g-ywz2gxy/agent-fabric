# -*- coding: utf-8 -*-
"""
注册表热加载模块

该模块提供了注册表文件变化检测和自动重载功能。
"""
from __future__ import annotations

from dataclasses import dataclass

from registry.transaction import RegistryTransactionManager


@dataclass(slots=True, frozen=True)
class HotReloadEvent:
    """
    热加载事件数据类
    
    表示一次热加载操作的结果。
    
    属性:
        changed: 文件是否发生变化
        applied: 是否成功应用更新
        rolled_back: 是否回滚
        error: 错误信息（如果有）
    """
    changed: bool  # 是否变化
    applied: bool  # 是否应用成功
    rolled_back: bool  # 是否回滚
    error: str | None = None  # 错误信息


class RegistryHotReloader:
    """
    注册表热加载器
    
    监控注册表文件的变化，并在检测到变化时自动重载。
    使用文件修改时间和大小作为变化检测依据。
    
    属性:
        _transaction_manager: 事务管理器实例
        _last_fingerprint: 上次检测时的文件指纹
    """
    def __init__(self, transaction_manager: RegistryTransactionManager) -> None:
        """
        初始化热加载器
        
        参数:
            transaction_manager: 注册表事务管理器实例
        """
        self._transaction_manager = transaction_manager
        self._last_fingerprint = self._fingerprint()  # 初始指纹

    def scan_and_reload(self, *, force: bool = False) -> HotReloadEvent:
        """
        扫描并重载注册表
        
        检查注册表文件是否发生变化，如果变化则触发重载。
        
        参数:
            force: 是否强制重载（忽略变化检测）
            
        返回:
            热加载事件结果
        """
        current = self._fingerprint()
        changed = force or current != self._last_fingerprint
        
        # 没有变化则直接返回
        if not changed:
            return HotReloadEvent(changed=False, applied=False, rolled_back=False)

        # 更新指纹并执行重载
        self._last_fingerprint = current
        result = self._transaction_manager.reload()
        return HotReloadEvent(
            changed=True,
            applied=result.success,
            rolled_back=result.rolled_back,
            error=result.error,
        )

    def _fingerprint(self) -> tuple[tuple[int, int], tuple[int, int]]:
        """
        计算文件指纹
        
        使用修改时间和大小作为文件指纹。
        
        返回:
            元组包含代理和技能注册表的指纹
        """
        agents = self._safe_stat(self._transaction_manager.agents_registry_path)
        skills = self._safe_stat(self._transaction_manager.skills_registry_path)
        return (agents, skills)

    @staticmethod
    def _safe_stat(path) -> tuple[int, int]:
        """
        安全获取文件状态
        
        获取文件的修改时间和大小，失败时返回 (-1, -1)。
        
        参数:
            path: 文件路径
            
        返回:
            元组包含修改时间(ns)和大小
        """
        try:
            stat_result = path.stat()
            return (stat_result.st_mtime_ns, stat_result.st_size)
        except FileNotFoundError:
            return (-1, -1)
