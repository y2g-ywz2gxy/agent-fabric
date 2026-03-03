# -*- coding: utf-8 -*-
"""
注册表模块

提供代理和技能的注册管理功能：
- RegistryEntry: 注册表条目
- RegistrySnapshot: 注册表快照
- RegistryTransactionManager: 事务管理器
- RegistryHotReloader: 热加载器
"""
from registry.config_loader import load_registry_snapshot
from registry.hot_reload import HotReloadEvent, RegistryHotReloader
from registry.schema import RegistryEntry, RegistrySnapshot, SchemaValidationError
from registry.transaction import RegistryTransactionManager, TransactionResult

__all__ = [
    "HotReloadEvent",
    "RegistryEntry",
    "RegistryHotReloader",
    "RegistrySnapshot",
    "RegistryTransactionManager",
    "SchemaValidationError",
    "TransactionResult",
    "load_registry_snapshot",
]