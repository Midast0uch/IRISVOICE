"""
Automation module - Native GUI control and Vision integration
"""
from .operator import NativeGUIOperator, OperatorResult
from .vision import VisionModelClient, GUIAgent, ElementDetection, VisionProvider

__all__ = [
    "NativeGUIOperator",
    "OperatorResult",
    "VisionModelClient",
    "GUIAgent",
    "ElementDetection",
    "VisionProvider"
]
