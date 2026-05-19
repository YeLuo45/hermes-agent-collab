"""
i18n Internationalization Framework for hermes-agent-collab.
Supports multiple locales, translation lookup, template interpolation, and language switching.
"""

from __future__ import annotations

import re
import json
from dataclasses import dataclass, field, asdict
from typing import Any


# ---------------------------------------------------------------------------
# Data Classes
# ---------------------------------------------------------------------------

@dataclass
class LocaleInfo:
    """Represents a supported locale/language."""
    code: str  # e.g., "en", "zh", "ja", "ko"
    name: str  # e.g., "English", "中文"
    native_name: str  # e.g., "English", "简体中文"
    is_rtl: bool = False  # Right-to-left language
    is_active: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class TranslationKey:
    """A translation key with translations across locales."""
    key: str
    translations: dict[str, str] = field(default_factory=dict)
    description: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Locale Detector
# ---------------------------------------------------------------------------

class LocaleDetector:
    """
    Detects user preferred locale from Accept-Language header.
    Follows BCP 47 / RFC 7231 Accept-Language parsing.
    """

    LOCALE_PRIORITY_RE = re.compile(
        r'([a-zA-Z]{1,8}(?:-[a-zA-Z0-9]{1,8})*)\s*(?:;\s*q\s*=\s*([0-9.]+))?'
    )

    def __init__(self, supported_locales: list[str]):
        self._supported = set(supported_locales)

    def detect(self, accept_language: str | None) -> str:
        """
        Detect best matching locale from Accept-Language header.
        Returns the supported locale with highest q-value.
        """
        if not accept_language:
            return "en"

        locale_q = []
        for m in self.LOCALE_PRIORITY_RE.finditer(accept_language):
            locale = m.group(1).split('-')[0].lower()  # Primary language tag
            q = float(m.group(2)) if m.group(2) else 1.0
            locale_q.append((locale, q))

        # Sort by q-value descending
        locale_q.sort(key=lambda x: -x[1])

        # Find first supported locale
        for locale, _ in locale_q:
            if locale in self._supported:
                return locale
            # Try full locale code (e.g., "zh-cn")
            full = m.group(1).lower()
            if full in self._supported:
                return full

        return "en"

    def is_supported(self, locale: str) -> bool:
        """Check if locale is supported."""
        return locale.lower() in self._supported

    def get_best_match(self, locales: list[str]) -> str | None:
        """Get best matching locale from a list of desired locales."""
        for locale in locales:
            if self.is_supported(locale):
                return locale
        return None


# ---------------------------------------------------------------------------
# i18n Manager
# ---------------------------------------------------------------------------

class I18nManager:
    """
    Manages locales, translations, and language switching.
    Singleton pattern via module-level instance.
    """

    _instance: I18nManager | None = None

    def __init__(self, default_locale: str = "en"):
        self._default_locale = default_locale
        self._current_locale = default_locale
        self._locales: dict[str, LocaleInfo] = {}
        self._translations: dict[str, dict[str, str]] = {}  # locale -> key -> translation
        self._detector: LocaleDetector | None = None
        self._namespace_separator = "."
        self._interpolation_pattern = re.compile(r'\{\{(\w+)\}\}')

        # Register built-in locales
        self._register_builtin_locales()

    def _register_builtin_locales(self):
        """Register the 4 built-in locales."""
        self.add_locale(LocaleInfo(code="en", name="English", native_name="English"))
        self.add_locale(LocaleInfo(code="zh", name="Chinese", native_name="简体中文"))
        self.add_locale(LocaleInfo(code="ja", name="Japanese", native_name="日本語"))
        self.add_locale(LocaleInfo(code="ko", name="Korean", native_name="한국어"))

        # Set zh as active
        self.activate_locale("en")
        self.activate_locale("zh")

        # Load built-in translations
        self._load_builtin_translations()

    def _load_builtin_translations(self):
        """Load built-in translation dictionaries."""
        # English (default)
        self._translations["en"] = {
            # General
            "general.ok": "OK",
            "general.cancel": "Cancel",
            "general.save": "Save",
            "general.delete": "Delete",
            "general.edit": "Edit",
            "general.create": "Create",
            "general.close": "Close",
            "general.loading": "Loading...",
            "general.error": "Error",
            "general.success": "Success",
            "general.warning": "Warning",
            "general.info": "Info",
            "general.confirm": "Confirm",
            "general.yes": "Yes",
            "general.no": "No",
            # Agent
            "agent.status.running": "Running",
            "agent.status.idle": "Idle",
            "agent.status.busy": "Busy",
            "agent.status.offline": "Offline",
            "agent.status.error": "Error",
            "agent.created": "Agent {{name}} created",
            "agent.deleted": "Agent {{name}} deleted",
            "agent.not_found": "Agent not found: {{id}}",
            # Task
            "task.status.pending": "Pending",
            "task.status.running": "Running",
            "task.status.completed": "Completed",
            "task.status.failed": "Failed",
            "task.status.cancelled": "Cancelled",
            "task.created": "Task {{name}} created",
            "task.completed": "Task {{name}} completed",
            "task.failed": "Task {{name}} failed: {{reason}}",
            "task.not_found": "Task not found: {{id}}",
            # Workspace
            "workspace.created": "Workspace {{name}} created",
            "workspace.deleted": "Workspace {{name}} deleted",
            "workspace.not_found": "Workspace not found: {{id}}",
            # Notification
            "notification.sent": "Notification sent via {{channel}}",
            "notification.failed": "Notification failed: {{reason}}",
            "notification.channel.registered": "Channel {{name}} registered",
            "notification.channel.unregistered": "Channel {{name}} unregistered",
            # Tracing
            "tracing.enabled": "Distributed tracing enabled",
            "tracing.disabled": "Distributed tracing disabled",
            "tracing.span.created": "Span {{name}} created",
            # Experiment
            "experiment.created": "Experiment {{name}} created",
            "experiment.started": "Experiment {{name}} started",
            "experiment.stopped": "Experiment {{name}} stopped",
            "experiment.completed": "Experiment {{name}} completed",
            "experiment.no_significant_result": "No statistically significant result",
            # Playground
            "playground.sandbox.created": "Sandbox {{id}} created",
            "playground.sandbox.deleted": "Sandbox {{id}} deleted",
            "playground.execution.timeout": "Execution timed out after {{seconds}}s",
            "playground.execution.error": "Execution error: {{error}}",
            # Knowledge Graph
            "kg.node.created": "Node {{id}} created",
            "kg.node.deleted": "Node {{id}} deleted",
            "kg.relationship.created": "Relationship {{id}} created",
            "kg.relationship.deleted": "Relationship {{id}} deleted",
            "kg.query.error": "Query error: {{reason}}",
            # Errors
            "error.not_found": "{{resource}} not found: {{id}}",
            "error.already_exists": "{{resource}} already exists: {{id}}",
            "error.invalid_request": "Invalid request: {{reason}}",
            "error.internal": "Internal error: {{reason}}",
            "error.unauthorized": "Unauthorized",
            "error.forbidden": "Forbidden",
            "error.bad_request": "Bad request: {{reason}}",
            # Validation
            "validation.required": "{{field}} is required",
            "validation.min_length": "{{field}} must be at least {{min}} characters",
            "validation.max_length": "{{field}} must be at most {{max}} characters",
            "validation.pattern": "{{field}} must match pattern {{pattern}}",
        }

        # Chinese (Simplified)
        self._translations["zh"] = {
            "general.ok": "确定",
            "general.cancel": "取消",
            "general.save": "保存",
            "general.delete": "删除",
            "general.edit": "编辑",
            "general.create": "创建",
            "general.close": "关闭",
            "general.loading": "加载中...",
            "general.error": "错误",
            "general.success": "成功",
            "general.warning": "警告",
            "general.info": "提示",
            "general.confirm": "确认",
            "general.yes": "是",
            "general.no": "否",
            "agent.status.running": "运行中",
            "agent.status.idle": "空闲",
            "agent.status.busy": "忙碌",
            "agent.status.offline": "离线",
            "agent.status.error": "错误",
            "agent.created": "Agent {{name}} 已创建",
            "agent.deleted": "Agent {{name}} 已删除",
            "agent.not_found": "Agent 未找到: {{id}}",
            "task.status.pending": "待处理",
            "task.status.running": "运行中",
            "task.status.completed": "已完成",
            "task.status.failed": "失败",
            "task.status.cancelled": "已取消",
            "task.created": "任务 {{name}} 已创建",
            "task.completed": "任务 {{name}} 已完成",
            "task.failed": "任务 {{name}} 失败: {{reason}}",
            "task.not_found": "任务未找到: {{id}}",
            "workspace.created": "工作空间 {{name}} 已创建",
            "workspace.deleted": "工作空间 {{name}} 已删除",
            "workspace.not_found": "工作空间未找到: {{id}}",
            "notification.sent": "通知已通过 {{channel}} 发送",
            "notification.failed": "通知发送失败: {{reason}}",
            "notification.channel.registered": "渠道 {{name}} 已注册",
            "notification.channel.unregistered": "渠道 {{name}} 已注销",
            "tracing.enabled": "分布式追踪已启用",
            "tracing.disabled": "分布式追踪已禁用",
            "tracing.span.created": "Span {{name}} 已创建",
            "experiment.created": "实验 {{name}} 已创建",
            "experiment.started": "实验 {{name}} 已启动",
            "experiment.stopped": "实验 {{name}} 已停止",
            "experiment.completed": "实验 {{name}} 已完成",
            "experiment.no_significant_result": "无统计显著结果",
            "playground.sandbox.created": "沙盒 {{id}} 已创建",
            "playground.sandbox.deleted": "沙盒 {{id}} 已删除",
            "playground.execution.timeout": "执行超时 ({{seconds}}秒)",
            "playground.execution.error": "执行错误: {{error}}",
            "kg.node.created": "节点 {{id}} 已创建",
            "kg.node.deleted": "节点 {{id}} 已删除",
            "kg.relationship.created": "关系 {{id}} 已创建",
            "kg.relationship.deleted": "关系 {{id}} 已删除",
            "kg.query.error": "查询错误: {{reason}}",
            "error.not_found": "{{resource}} 未找到: {{id}}",
            "error.already_exists": "{{resource}} 已存在: {{id}}",
            "error.invalid_request": "无效请求: {{reason}}",
            "error.internal": "内部错误: {{reason}}",
            "error.unauthorized": "未授权",
            "error.forbidden": "禁止访问",
            "error.bad_request": "错误请求: {{reason}}",
            "validation.required": "{{field}} 为必填项",
            "validation.min_length": "{{field}} 长度不能少于 {{min}} 个字符",
            "validation.max_length": "{{field}} 长度不能超过 {{max}} 个字符",
            "validation.pattern": "{{field}} 必须符合格式 {{pattern}}",
        }

        # Japanese
        self._translations["ja"] = {
            "general.ok": "OK",
            "general.cancel": "キャンセル",
            "general.save": "保存",
            "general.delete": "削除",
            "general.edit": "編集",
            "general.create": "作成",
            "general.close": "閉じる",
            "general.loading": "読み込み中...",
            "general.error": "エラー",
            "general.success": "成功",
            "general.warning": "警告",
            "general.info": "情報",
            "general.confirm": "確認",
            "general.yes": "はい",
            "general.no": "いいえ",
            "agent.status.running": "実行中",
            "agent.status.idle": "待機中",
            "agent.status.busy": "多忙",
            "agent.status.offline": "オフライン",
            "agent.status.error": "エラー",
            "agent.created": "エージェント {{name}} を作成しました",
            "agent.deleted": "エージェント {{name}} を削除しました",
            "agent.not_found": "エージェントが見つかりません: {{id}}",
            "task.status.pending": "保留中",
            "task.status.running": "実行中",
            "task.status.completed": "完了",
            "task.status.failed": "失敗",
            "task.status.cancelled": "キャンセル済み",
            "task.created": "タスク {{name}} を作成しました",
            "task.completed": "タスク {{name}} が完了しました",
            "task.failed": "タスク {{name}} が失敗しました: {{reason}}",
            "task.not_found": "タスクが見つかりません: {{id}}",
            "workspace.created": "ワークスペース {{name}} を作成しました",
            "workspace.deleted": "ワークスペース {{name}} を削除しました",
            "workspace.not_found": "ワークスペースが見つかりません: {{id}}",
            "notification.sent": "通知を {{channel}} 経由で送信しました",
            "notification.failed": "通知の送信に失敗しました: {{reason}}",
            "notification.channel.registered": "チャンネル {{name}} を登録しました",
            "notification.channel.unregistered": "チャンネル {{name}} を登録解除しました",
            "tracing.enabled": "分散トレースを有効化しました",
            "tracing.disabled": "分散トレースを無効化しました",
            "tracing.span.created": "Span {{name}} を作成しました",
            "experiment.created": "実験 {{name}} を作成しました",
            "experiment.started": "実験 {{name}} を開始しました",
            "experiment.stopped": "実験 {{name}} を停止しました",
            "experiment.completed": "実験 {{name}} が完了しました",
            "experiment.no_significant_result": "統計的に有意な結果がありません",
            "playground.sandbox.created": "サンドボックス {{id}} を作成しました",
            "playground.sandbox.deleted": "サンドボックス {{id}} を削除しました",
            "playground.execution.timeout": "実行がタイムアウトしました ({{seconds}}秒)",
            "playground.execution.error": "実行エラー: {{error}}",
            "kg.node.created": "ノード {{id}} を作成しました",
            "kg.node.deleted": "ノード {{id}} を削除しました",
            "kg.relationship.created": "リレーションシップ {{id}} を作成しました",
            "kg.relationship.deleted": "リレーションシップ {{id}} を削除しました",
            "kg.query.error": "クエリエラー: {{reason}}",
            "error.not_found": "{{resource}} が見つかりません: {{id}}",
            "error.already_exists": "{{resource}} が既に存在します: {{id}}",
            "error.invalid_request": "無効なリクエスト: {{reason}}",
            "error.internal": "内部エラー: {{reason}}",
            "error.unauthorized": "未認証",
            "error.forbidden": "禁止されています",
            "error.bad_request": "不正なリクエスト: {{reason}}",
            "validation.required": "{{field}} は必須です",
            "validation.min_length": "{{field}} は{{min}}文字以上である必要があります",
            "validation.max_length": "{{field}} は{{max}}文字以下である必要があります",
            "validation.pattern": "{{field}} はパターン {{pattern}} に一致する必要があります",
        }

        # Korean
        self._translations["ko"] = {
            "general.ok": "확인",
            "general.cancel": "취소",
            "general.save": "저장",
            "general.delete": "삭제",
            "general.edit": "편집",
            "general.create": "생성",
            "general.close": "닫기",
            "general.loading": "로딩 중...",
            "general.error": "오류",
            "general.success": "성공",
            "general.warning": "경고",
            "general.info": "정보",
            "general.confirm": "확인",
            "general.yes": "예",
            "general.no": "아니오",
            "agent.status.running": "실행 중",
            "agent.status.idle": "대기 중",
            "agent.status.busy": "바쁨",
            "agent.status.offline": "오프라인",
            "agent.status.error": "오류",
            "agent.created": "에이전트 {{name}} 생성됨",
            "agent.deleted": "에이전트 {{name}} 삭제됨",
            "agent.not_found": "에이전트를 찾을 수 없음: {{id}}",
            "task.status.pending": "대기 중",
            "task.status.running": "실행 중",
            "task.status.completed": "완료",
            "task.status.failed": "실패",
            "task.status.cancelled": "취소됨",
            "task.created": "태스크 {{name}} 생성됨",
            "task.completed": "태스크 {{name}} 완료됨",
            "task.failed": "태스크 {{name}} 실패: {{reason}}",
            "task.not_found": "태스크를 찾을 수 없음: {{id}}",
            "workspace.created": "워크스페이스 {{name}} 생성됨",
            "workspace.deleted": "워크스페이스 {{name}} 삭제됨",
            "workspace.not_found": "워크스페이스를 찾을 수 없음: {{id}}",
            "notification.sent": "알림이 {{channel}}을 통해 전송됨",
            "notification.failed": "알림 전송 실패: {{reason}}",
            "notification.channel.registered": "채널 {{name}} 등록됨",
            "notification.channel.unregistered": "채널 {{name}} 등록 해제됨",
            "tracing.enabled": "분산 추적 활성화됨",
            "tracing.disabled": "분산 추적 비활성화됨",
            "tracing.span.created": "스팬 {{name}} 생성됨",
            "experiment.created": "실험 {{name}} 생성됨",
            "experiment.started": "실험 {{name}} 시작됨",
            "experiment.stopped": "실험 {{name}} 중지됨",
            "experiment.completed": "실험 {{name}} 완료됨",
            "experiment.no_significant_result": "통계적으로 유의한 결과 없음",
            "playground.sandbox.created": "샌드박스 {{id}} 생성됨",
            "playground.sandbox.deleted": "샌드박스 {{id}} 삭제됨",
            "playground.execution.timeout": "실행 시간 초과 ({{seconds}}초)",
            "playground.execution.error": "실행 오류: {{error}}",
            "kg.node.created": "노드 {{id}} 생성됨",
            "kg.node.deleted": "노드 {{id}} 삭제됨",
            "kg.relationship.created": "관계 {{id}} 생성됨",
            "kg.relationship.deleted": "관계 {{id}} 삭제됨",
            "kg.query.error": "쿼리 오류: {{reason}}",
            "error.not_found": "{{resource}}을(를) 찾을 수 없음: {{id}}",
            "error.already_exists": "{{resource}}이(가) 이미 존재함: {{id}}",
            "error.invalid_request": "잘못된 요청: {{reason}}",
            "error.internal": "내부 오류: {{reason}}",
            "error.unauthorized": "인증되지 않음",
            "error.forbidden": "금지됨",
            "error.bad_request": "잘못된 요청: {{reason}}",
            "validation.required": "{{field}}은(는) 필수입니다",
            "validation.min_length": "{{field}}은(는) 최소 {{min}}자 이상이어야 합니다",
            "validation.max_length": "{{field}}은(는) 최대 {{max}}자 이하여야 합니다",
            "validation.pattern": "{{field}}은(는) 패턴 {{pattern}}과(와) 일치해야 합니다",
        }

    @classmethod
    def get_instance(cls) -> I18nManager:
        """Get singleton instance."""
        if cls._instance is None:
            cls._instance = I18nManager()
        return cls._instance

    def add_locale(self, locale: LocaleInfo) -> bool:
        """Register a new locale."""
        if locale.code in self._locales:
            return False
        self._locales[locale.code] = locale
        if locale.code not in self._translations:
            self._translations[locale.code] = {}
        self._detector = None  # Reset detector
        return True

    def activate_locale(self, code: str) -> bool:
        """Activate a locale (mark as available for use)."""
        if code not in self._locales:
            return False
        self._locales[code].is_active = True
        return True

    def deactivate_locale(self, code: str) -> bool:
        """Deactivate a locale."""
        if code not in self._locales:
            return False
        self._locales[code].is_active = False
        return True

    def add_translations(self, locale: str, translations: dict[str, str]):
        """Add translation key-value pairs for a locale."""
        if locale not in self._translations:
            self._translations[locale] = {}
        self._translations[locale].update(translations)

    def get_translation(self, key: str, locale: str | None = None) -> str:
        """
        Get translation for a key.
        Falls back to default locale if key not found in requested locale.
        """
        target_locale = locale or self._current_locale

        # Try target locale
        if target_locale in self._translations:
            if key in self._translations[target_locale]:
                return self._translations[target_locale][key]

        # Fall back to default locale
        if target_locale != self._default_locale:
            if self._default_locale in self._translations:
                if key in self._translations[self._default_locale]:
                    return self._translations[self._default_locale][key]

        # Return key itself if not found
        return key

    def set_locale(self, locale: str) -> bool:
        """Switch current locale."""
        if locale not in self._locales:
            return False
        self._current_locale = locale
        return True

    def get_locale(self) -> str:
        """Get current locale code."""
        return self._current_locale

    def get_default_locale(self) -> str:
        """Get default locale code."""
        return self._default_locale

    def get_available_locales(self) -> list[LocaleInfo]:
        """List all available (registered) locales."""
        return [loc for loc in self._locales.values()]

    def get_active_locales(self) -> list[LocaleInfo]:
        """List all active (enabled) locales."""
        return [loc for loc in self._locales.values() if loc.is_active]

    def translate_template(self, template: str, **kwargs: Any) -> str:
        """
        Translate a template string with variable interpolation.
        Supports {{variable}} format.
        """
        result = self.get_translation(template)
        if result == template:
            # Key not found, try interpolation directly
            result = template

        # Interpolate variables
        def replacer(m):
            var_name = m.group(1)
            return str(kwargs.get(var_name, m.group(0)))

        return self._interpolation_pattern.sub(replacer, result)

    def t(self, key: str, **kwargs: Any) -> str:
        """
        Short alias for get_translation with interpolation.
        Usage: i18n.t("agent.created", name="MyAgent")
        """
        result = self.get_translation(key)
        if kwargs:
            def replacer(m):
                var_name = m.group(1)
                return str(kwargs.get(var_name, m.group(0)))
            result = self._interpolation_pattern.sub(replacer, result)
        return result

    def detect_locale(self, accept_language: str | None) -> str:
        """Detect locale from Accept-Language header."""
        if self._detector is None:
            self._detector = LocaleDetector(list(self._locales.keys()))
        return self._detector.detect(accept_language)

    def get_translations_for_locale(self, locale: str) -> dict[str, str]:
        """Get all translations for a locale."""
        return self._translations.get(locale, {})

    def to_dict(self) -> dict:
        """Export all translations as nested dict."""
        return {
            "default_locale": self._default_locale,
            "current_locale": self._current_locale,
            "locales": {code: loc.to_dict() for code, loc in self._locales.items()},
            "translations": dict(self._translations),
        }

    def to_json(self, indent: int = 2) -> str:
        """Export all translations as JSON string."""
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)

    def export_locale_json(self, locale: str, indent: int = 2) -> str:
        """Export a single locale's translations as JSON."""
        translations = self.get_translations_for_locale(locale)
        return json.dumps({
            "locale": locale,
            "translations": translations,
        }, indent=indent, ensure_ascii=False)

    def import_translations(self, locale: str, json_str: str) -> int:
        """Import translations from JSON string. Returns number of keys imported."""
        try:
            data = json.loads(json_str)
            if "translations" in data:
                translations = data["translations"]
            elif isinstance(data, dict) and locale in data:
                translations = data[locale]
            else:
                translations = data
            self.add_translations(locale, translations)
            return len(translations)
        except json.JSONDecodeError:
            raise ValueError(f"Invalid JSON for locale {locale}")

    def get_untranslated_keys(self, locale: str) -> list[str]:
        """Get keys that are missing translation for a given locale."""
        default_keys = set(self._translations.get(self._default_locale, {}).keys())
        locale_keys = set(self._translations.get(locale, {}).keys())
        return sorted(default_keys - locale_keys)

    def get_translation_count(self, locale: str) -> int:
        """Get number of translated keys for a locale."""
        return len(self._translations.get(locale, {}))


# ---------------------------------------------------------------------------
# Module-level singleton accessor
# ---------------------------------------------------------------------------

_i18n_manager: I18nManager | None = None


def get_i18n_manager() -> I18nManager:
    """Get the global I18nManager singleton instance."""
    global _i18n_manager
    if _i18n_manager is None:
        _i18n_manager = I18nManager.get_instance()
    return _i18n_manager
