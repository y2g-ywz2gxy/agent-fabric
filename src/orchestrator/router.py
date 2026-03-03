# -*- coding: utf-8 -*-
"""
路由器模块

该模块提供了基于关键字的路由器实现，负责根据用户查询
识别场景并匹配相应的能力和执行单元。
"""
from __future__ import annotations

from orchestrator.result import ExecutionResult
from registry.schema import RegistryEntry, RegistrySnapshot


class KeywordRouter:
    """
    关键字路由器
    
    基于预定义的关键字规则进行场景识别和能力匹配。
    支持金融、支持、调研等场景的自动识别。
    
    属性:
        _SCENE_RULES: 场景规则元组，定义场景、关键字和能力映射
    """
    # 场景规则定义：(场景名称, 关键字元组, 所需能力元组)
    _SCENE_RULES: tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...] = (
        (
            "finance",  # 金融场景
            ("预算", "报销", "发票", "财务", "成本"),  # 金融相关关键字
            ("finance.analysis", "planning.decompose"),  # 所需能力
        ),
        (
            "support",  # 支持场景
            ("故障", "报错", "无法", "超时", "异常", "修复"),  # 支持相关关键字
            ("support.troubleshoot", "recovery.heal"),  # 所需能力
        ),
        (
            "research",  # 调研场景
            ("调研", "研究", "报告", "竞品", "市场"),  # 调研相关关键字
            ("research.rag", "planning.decompose"),  # 所需能力
        ),
    )

    def __init__(self, fallback_capability: str = "general.assistant") -> None:
        """
        初始化关键字路由器
        
        参数:
            fallback_capability: 默认回退能力，当无法匹配任何场景时使用
        """
        self._fallback_capability = fallback_capability

    def route(self, query: str, registry_snapshot: RegistrySnapshot) -> ExecutionResult:
        """
        执行路由逻辑
        
        根据用户查询识别场景，匹配注册表中的能力和执行单元。
        
        参数:
            query: 用户查询字符串
            registry_snapshot: 注册表快照
            
        返回:
            包含场景、能力和候选执行单元的执行结果
        """
        normalized = query.strip()  # 规范化查询字符串
        if not normalized:
            return ExecutionResult.failure("Routing failed: query is empty.")

        # 推断场景和所需能力
        scene, required_capabilities = self._infer_scene(normalized)
        # 从注册表中查找匹配的条目
        matched_entries = registry_snapshot.find_by_capabilities(required_capabilities)

        if matched_entries:
            # 提取匹配的能力列表
            matched_capabilities = sorted(
                {
                    capability
                    for entry in matched_entries
                    for capability in entry.capabilities
                    if capability in set(required_capabilities)
                }
            )
        else:
            # 没有匹配时使用回退能力
            matched_capabilities = [self._fallback_capability]

        # 构建返回结果
        payload = {
            "scene": scene,  # 识别的场景
            "required_capabilities": list(required_capabilities),  # 所需能力
            "matched_capabilities": matched_capabilities,  # 匹配的能力
            "candidates": [self._entry_to_payload(entry) for entry in matched_entries],  # 候选执行单元
        }
        return ExecutionResult.success(payload, next_action="plan")

    def _infer_scene(self, query: str) -> tuple[str, tuple[str, ...]]:
        """
        推断查询所属场景
        
        根据关键字规则判断查询属于哪个场景。
        
        参数:
            query: 用户查询字符串
            
        返回:
            元组包含场景名称和所需能力列表
        """
        lowered = query.lower()
        for scene, keywords, capabilities in self._SCENE_RULES:
            if any(keyword in lowered for keyword in keywords):
                return scene, capabilities
        # 未匹配任何场景时返回通用场景
        return "generic", (self._fallback_capability,)

    @staticmethod
    def _entry_to_payload(entry: RegistryEntry) -> dict[str, object]:
        """
        将注册表条目转换为返回数据格式
        
        参数:
            entry: 注册表条目
            
        返回:
            包含条目信息的字典
        """
        return {
            "id": entry.id,
            "source": entry.source,
            "capabilities": list(entry.capabilities),
            "entrypoint": entry.entrypoint,
            "healthcheck": entry.healthcheck,
            "version": entry.version,
        }
