"""Pydantic request and response schemas for the public API."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field

from .models import JobStatus, UserRole


class UserOut(BaseModel):
    id: UUID
    username: str
    email: EmailStr
    display_name: str
    role: UserRole
    is_active: bool = True
    deletion_pending: bool = False


class AdminUserCreateIn(BaseModel):
    username: str = Field(min_length=3, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{2,63}$")
    password: str = Field(min_length=8, max_length=256)
    password_confirmation: str = Field(min_length=8, max_length=256)


class AdminUserUpdateIn(BaseModel):
    role: UserRole | None = None
    is_active: bool | None = None


class LoginIn(BaseModel):
    username: str = Field(
        min_length=3,
        max_length=64,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{2,63}$",
    )
    password: str = Field(min_length=8, max_length=256)


class InviteIn(BaseModel):
    email: EmailStr


class InviteOut(BaseModel):
    id: UUID
    email: EmailStr
    token: str
    expires_at: datetime


class RegisterIn(BaseModel):
    token: str = Field(min_length=20, max_length=512)
    username: str = Field(
        min_length=3,
        max_length=64,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{2,63}$",
    )
    display_name: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=8, max_length=256)


class ProjectCreateIn(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    skill_id: str = Field(
        default="ppt-master", max_length=64, pattern=r"^[a-z0-9][a-z0-9-]*$"
    )
    # Creation mode for skills that expose several flows (draft/typeset…);
    # validated against the skill manifest and then frozen on the project.
    mode: str | None = Field(default=None, max_length=32, pattern=r"^[a-z0-9][a-z0-9-]*$")
    prompt_snippet_id: UUID | None = None


class ProjectCoverOut(BaseModel):
    """Points the dashboard card at the first previewable page of a project."""

    job_id: UUID
    artifact_id: UUID
    kind: str


class ProjectOut(BaseModel):
    id: UUID
    title: str
    skill_id: str
    mode: str | None = None
    created_at: datetime
    updated_at: datetime
    cover: ProjectCoverOut | None = None


class ProjectMaterialOut(BaseModel):
    id: UUID
    original_filename: str
    content_type: str
    size_bytes: int
    status: str
    metadata: dict
    error: str | None
    created_at: datetime
    updated_at: datetime


class ProjectUpdateIn(BaseModel):
    title: str = Field(min_length=1, max_length=160)


class OutlineSlideIn(BaseModel):
    """PPT-shaped outline item, kept for preset generation endpoints."""

    title: str = Field(min_length=1, max_length=160)
    purpose: str = Field(default="", max_length=500)
    content: str = Field(default="", max_length=4_000)
    kind: str = Field(default="内容页", max_length=64)
    notes: str = Field(default="", max_length=2_000)


class ProjectCreativeStateUpdateIn(BaseModel):
    stage: str | None = Field(default=None, max_length=32)
    requirements: dict | None = None
    # Items are validated per skill against the skill manifest's outline fields.
    outline: list[dict] | None = None
    notes_enabled: bool | None = None
    selected_template_id: UUID | None = None


class ProjectCreativeOutlineIn(BaseModel):
    """Request a fresh outline from the saved creative requirements."""

    requirements: dict | None = None


class PromptPresetOutlineGenerateIn(BaseModel):
    """Request a draft outline for a creation preset before it is saved."""

    requirements: dict = Field(default_factory=dict)


class ProjectCreativeRequirementsInferIn(BaseModel):
    """Ask the model to draft an initial structured requirements guess.

    ``draft`` is the raw text the user typed in the home composer before any
    field-by-field editing; only called once, right after project creation,
    and only when no saved preset already supplied structured requirements.
    """

    draft: str = Field(min_length=1, max_length=20_000)


class ProjectCreativeStateOut(BaseModel):
    project_id: UUID
    stage: str
    requirements: dict
    outline: list[dict]
    notes_enabled: bool
    selected_template_id: UUID | None
    updated_at: datetime | None


class PageRefinementMessageOut(BaseModel):
    id: UUID
    job_id: UUID | None
    slide_number: int
    role: str
    content: str
    message_order: int
    created_at: datetime


class PageRefinementIntentIn(BaseModel):
    """Classify one chat message before creating a refinement job.

    ``slide_number`` follows the creation scope: 1..999 targets one PPT page,
    while 0 is the document-wide conversation for document-refinement skills.
    """

    slide_number: int = Field(ge=0, le=999)
    slide_title: str = Field(default="当前页面", min_length=1, max_length=200)
    message: str = Field(min_length=1, max_length=4_000)
    client_message_id: str | None = Field(default=None, min_length=8, max_length=64)


class PageRefinementIntentOut(BaseModel):
    action: str
    confidence: float = Field(ge=0, le=1)
    normalized_request: str = ""
    reply: str = ""
    clarification_question: str = ""


class TemplateOut(BaseModel):
    id: UUID
    name: str
    original_filename: str
    status: str
    page_count: int | None
    metadata: dict
    error: str | None
    created_at: datetime
    updated_at: datetime
    scope: str = "user"
    is_active: bool = True
    sort_order: int = 0


class TemplateRenameIn(BaseModel):
    name: str = Field(min_length=1, max_length=160)


class AdminTemplateUpdateIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    is_active: bool | None = None
    sort_order: int | None = None


class PromptSnippetCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    content: str = Field(default="", max_length=10_000)
    category: str = Field(default="个人", min_length=1, max_length=64)
    preset: dict = Field(default_factory=dict)


class PromptSnippetUpdateIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    content: str | None = Field(default=None, max_length=10_000)
    category: str | None = Field(default=None, min_length=1, max_length=64)
    preset: dict | None = None


class PromptSnippetOut(BaseModel):
    id: UUID
    name: str
    content: str
    category: str
    used_count: int
    created_at: datetime
    updated_at: datetime
    scope: str = "user"
    is_active: bool = True
    sort_order: int = 0
    preset: dict = Field(default_factory=dict)
    # NULL means the preset applies to every skill.
    skill_id: str | None = None


class AdminPromptSnippetCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    content: str = Field(default="", max_length=10_000)
    category: str = Field(default="平台", min_length=1, max_length=64)
    is_active: bool = True
    sort_order: int = 0
    preset: dict = Field(default_factory=dict)
    # Empty string means universal; absent stays default (ppt-master on create).
    skill_id: str = "ppt-master"


class AdminPromptSnippetUpdateIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    content: str | None = Field(default=None, max_length=10_000)
    category: str | None = Field(default=None, min_length=1, max_length=64)
    is_active: bool | None = None
    sort_order: int | None = None
    preset: dict | None = None
    # Only applied when the client sends the field; empty string means universal.
    skill_id: str | None = None


class JobCreateIn(BaseModel):
    prompt: str = Field(min_length=1, max_length=20_000)
    model: str | None = Field(default=None, max_length=255)
    template_id: UUID | None = None
    base_job_id: UUID | None = None
    resume_from_cancelled: bool = False
    target_slide_number: int | None = Field(default=None, ge=1, le=999)
    conversation_message: str | None = Field(default=None, min_length=1, max_length=4_000)
    client_message_id: str | None = Field(default=None, min_length=8, max_length=64)


class JobOut(BaseModel):
    id: UUID
    project_id: UUID
    base_job_id: UUID | None
    resumed_by_job_id: UUID | None
    skill_id: str
    mode: str | None = None
    target_slide_number: int | None
    template_id: UUID | None
    template_name: str | None
    status: JobStatus
    prompt: str
    model: str | None
    error: str | None
    cancellation_requested: bool
    created_at: datetime


class ModelOut(BaseModel):
    id: str
    is_default: bool = False


class ModelCatalogOut(BaseModel):
    model_id: str
    source: str
    provider_id: UUID | None = None
    provider_display_name: str | None = None
    is_available: bool
    is_default: bool


class ModelCatalogDefaultIn(BaseModel):
    model_id: str = Field(min_length=1, max_length=255)


class ProviderModelIn(BaseModel):
    model_id: str = Field(min_length=1, max_length=255)
    display_name: str = Field(min_length=1, max_length=160)
    is_active: bool = True


class ProviderModelUpdateIn(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=160)
    is_active: bool | None = None
    is_default: bool | None = None


class ProviderIn(BaseModel):
    slug: str = Field(min_length=2, max_length=64, pattern=r"^[a-z][a-z0-9_-]*$")
    display_name: str = Field(min_length=1, max_length=120)
    base_url: str = Field(min_length=8, max_length=1024)
    api_key: str = Field(min_length=1, max_length=4096)
    is_active: bool = True


class ProviderUpdateIn(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=120)
    base_url: str | None = Field(default=None, min_length=8, max_length=1024)
    api_key: str | None = Field(default=None, min_length=1, max_length=4096)
    is_active: bool | None = None


class ProviderModelOut(BaseModel):
    id: UUID
    model_id: str
    display_name: str
    is_active: bool
    is_default: bool
    is_verified: bool
    last_tested_at: datetime | None
    last_test_error: str | None


class ProviderOut(BaseModel):
    id: UUID
    slug: str
    display_name: str
    base_url: str
    api_key_hint: str
    is_active: bool
    models: list[ProviderModelOut]


class ModelConnectivityTestIn(BaseModel):
    """Temporary provider/model credentials used only for a connectivity check."""

    slug: str = Field(min_length=2, max_length=64, pattern=r"^[a-z][a-z0-9_-]*$")
    display_name: str = Field(min_length=1, max_length=120)
    base_url: str = Field(min_length=8, max_length=1024)
    api_key: str = Field(min_length=1, max_length=4096)
    model_id: str = Field(min_length=1, max_length=255)


class ModelConnectivityTestOut(BaseModel):
    success: bool
    message: str
    tested_at: datetime


class ExistingProviderModelConnectivityTestIn(BaseModel):
    model_id: str = Field(min_length=1, max_length=255)


class ModelStatusOut(BaseModel):
    configured: bool
    model_id: str | None
    provider_display_name: str | None
    message: str


class JobEventOut(BaseModel):
    id: int
    event_type: str
    payload: dict
    created_at: datetime


class ArtifactOut(BaseModel):
    id: UUID
    kind: str
    filename: str
    content_type: str
    size_bytes: int
    created_at: datetime


class EditorSlideOut(BaseModel):
    """Describe one SVG source page available to the browser editor."""

    id: UUID
    filename: str
    size_bytes: int


class EditorSlideSaveIn(BaseModel):
    """Carry one complete, browser-edited SVG document."""

    content: str = Field(min_length=1, max_length=3_000_000)


class SkillStageOut(BaseModel):
    id: str
    label: str
    description: str = ""


class SkillOutlineFieldOut(BaseModel):
    name: str
    label: str
    required: bool = False
    max_length: int | None = None
    default: str = ""


class SkillOutlineOut(BaseModel):
    item_label: str = "项"
    generator_prompt_key: str | None = None
    fields: list[SkillOutlineFieldOut] = Field(default_factory=list)
    first_item_is_title_page: bool = False


class SkillModeFieldOut(BaseModel):
    """One form field of a creation mode's pre-generation panel."""

    name: str
    label: str
    type: str = "text"
    required: bool = False
    max_length: int | None = None
    default: str = ""
    placeholder: str = ""
    options: list[str] = Field(default_factory=list)
    wide: bool = False


class SkillModeOut(BaseModel):
    """One creation flow (draft/typeset…) with its own stages and form."""

    id: str
    label: str
    description: str = ""
    composer_placeholder: str = ""
    stages: list[SkillStageOut] = Field(default_factory=list)
    fields: list[SkillModeFieldOut] = Field(default_factory=list)


class SkillRefinementOut(BaseModel):
    """Chat-refinement labels; ``scope`` is page (PPT) or document (公文)."""

    scope: str = "page"
    assistant_name: str = "AI 页面助手"
    scope_label: str = "当前页"
    context_hint: str = "只会修改当前页，其他页面保持不变。"
    empty_hint: str = "告诉我想如何修改当前页…"


class SkillFeaturesOut(BaseModel):
    templates: bool = False
    page_refinement: bool = False
    document_refinement: bool = False
    editor: bool = False
    materials_upload: bool = True
    resume: bool = True


class SkillFrontendOut(BaseModel):
    hero_title: str = ""
    hero_subtitle: str = ""
    composer_placeholder: str = ""
    create_button_label: str = ""
    projects_nav_label: str = ""
    quick_starts: list[str] = Field(default_factory=list)
    stages: list[SkillStageOut] = Field(default_factory=list)
    modes: list[SkillModeOut] = Field(default_factory=list)
    refinement: SkillRefinementOut = Field(default_factory=SkillRefinementOut)
    outline: SkillOutlineOut = Field(default_factory=SkillOutlineOut)
    preview_kinds: list[str] = Field(default_factory=lambda: ["svg"])


class SkillOut(BaseModel):
    """One registered skill as exposed to the frontend work-type switch."""

    id: str
    display_name: str
    description: str = ""
    icon: str = ""
    enabled: bool = True
    primary_artifact_kind: str = ""
    features: SkillFeaturesOut = Field(default_factory=SkillFeaturesOut)
    frontend: SkillFrontendOut = Field(default_factory=SkillFrontendOut)
