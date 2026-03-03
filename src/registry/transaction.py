# -*- coding: utf-8 -*-
"""
注册表事务管理模块

该模块提供了注册表的事务性加载和管理功能，确保
注册表更新的原子性和线程安全。
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from threading import RLock

from registry.config_loader import load_registry_snapshot
from registry.schema import RegistrySnapshot


@dataclass(slots=True, frozen=True)
class TransactionResult:
    """
    事务结果数据类
    
    表示注册表事务的执行结果。
    
    属性:
        success: 是否成功
        snapshot: 当前注册表快照
        rolled_back: 是否回滚
        error: 错误信息（如果有）
    """
    success: bool  # 是否成功
    snapshot: RegistrySnapshot  # 当前快照
    rolled_back: bool  # 是否回滚
    error: str | None = None  # 错误信息


class RegistryTransactionManager:
    """
    注册表事务管理器
    
    提供注册表的线程安全访问和原子性更新。
    使用可重入锁确保线程安全。
    
    属性:
        _agents_registry_path: 代理注册表文件路径
        _skills_registry_path: 技能注册表文件路径
        _lock: 可重入锁
        _snapshot: 当前注册表快照
    """
    def __init__(self, agents_registry_path: str | Path, skills_registry_path: str | Path) -> None:
        """
        初始化事务管理器
        
        参数:
            agents_registry_path: 代理注册表文件路径
            skills_registry_path: 技能注册表文件路径
        """
        self._agents_registry_path = Path(agents_registry_path)
        self._skills_registry_path = Path(skills_registry_path)
        self._lock = RLock()  # 可重入锁
        # 初始加载注册表
        self._snapshot = load_registry_snapshot(
            self._agents_registry_path,
            self._skills_registry_path,
        )

    @property
    def agents_registry_path(self) -> Path:
        """获取代理注册表文件路径"""
        return self._agents_registry_path

    @property
    def skills_registry_path(self) -> Path:
        """获取技能注册表文件路径"""
        return self._skills_registry_path

    def get_snapshot(self) -> RegistrySnapshot:
        """
        获取当前注册表快照
        
        线程安全地获取当前注册表状态。
        
        返回:
            当前注册表快照
        """
        with self._lock:
            return self._snapshot

    def reload(self) -> TransactionResult:
        """
        重新加载注册表
        
        原子性地更新注册表快照。如果加载失败，保持原有快照不变。
        
        返回:
            事务结果
        """
        with self._lock:
            previous = self._snapshot  # 保存当前快照
            try:
                # 尝试加载新快照
                staged = load_registry_snapshot(
                    self._agents_registry_path,
                    self._skills_registry_path,
                )
            except Exception as exc:
                # 加载失败，返回错误结果（保持原快照）
                return TransactionResult(
                    success=False,
                    snapshot=previous,
                    rolled_back=True,
                    error=str(exc),
                )

            # 更新快照
            self._snapshot = staged
            return TransactionResult(success=True, snapshot=staged, rolled_back=False)
