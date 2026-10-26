"""Identity: users, the pre-registered ID registry and the profiles that exist before signup."""

from django.conf import settings
from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.core.validators import RegexValidator
from django.db import models
from django.utils import timezone
from django.utils.functional import cached_property
from django.utils.translation import gettext_lazy as _

from apps.accounts.services.identifiers import normalize_phone, normalize_registry_id
from apps.accounts.services.username import generate_username
from apps.core.encryption import EncryptedCharField, blind_index
from apps.core.permissions import Role

EMAIL_INDEX_PURPOSE = "user.contact_email"
PHONE_INDEX_PURPOSE = "user.contact_phone"
REGISTRY_INDEX_PURPOSE = "registry.external_id"


class UserManager(BaseUserManager):
    use_in_migrations = True

    def create_user(self, role, password=None, **fields):
        """Create a user with a freshly generated username (usernames are never chosen)."""
        if role not in Role.values:
            raise ValueError(f"Unknown role {role!r}.")
        user = self.model(username=generate_username(role), role=role, **fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_admin(self, password, **fields):
        return self.create_user(Role.ADMIN, password, **fields)


class User(AbstractBaseUser):
    username = models.CharField(
        _("username"),
        max_length=32,
        unique=True,
        editable=False,
        validators=[RegexValidator(r"^[a-z]{3}_[a-z0-9]+$")],
        help_text=_("Issued by the system and never changes."),
    )
    role = models.CharField(_("role"), max_length=16, choices=Role.choices)
    department = models.ForeignKey(
        "academics.Department",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="users",
        verbose_name=_("department"),
    )
    nickname = models.CharField(_("nickname"), max_length=50, blank=True)
    language = models.CharField(
        _("language"), max_length=8, choices=settings.LANGUAGES, default=settings.LANGUAGE_CODE
    )
    avatar = models.ImageField(_("avatar"), upload_to="avatars/", blank=True)

    contact_email = EncryptedCharField(_("contact e-mail"), max_length=254, null=True, blank=True)
    contact_email_index = models.CharField(  # noqa: DJ001 - NULL keeps "no e-mail" out of the unique index
        max_length=64, null=True, unique=True, editable=False
    )
    contact_phone = EncryptedCharField(_("contact phone"), max_length=32, null=True, blank=True)
    contact_phone_index = models.CharField(  # noqa: DJ001 - NULL keeps "no phone" out of the unique index
        max_length=64, null=True, unique=True, editable=False
    )

    totp_secret = EncryptedCharField(_("TOTP secret"), max_length=64, null=True, blank=True)
    totp_enabled = models.BooleanField(_("two-factor enabled"), default=False)

    is_active = models.BooleanField(_("active"), default=True)
    date_joined = models.DateTimeField(_("date joined"), default=timezone.now)

    objects = UserManager()

    USERNAME_FIELD = "username"

    class Meta:
        verbose_name = _("user")
        verbose_name_plural = _("users")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_username = None if self._state.adding else self.__dict__.get("username")

    def __str__(self):
        return self.username

    @property
    def is_staff(self):
        """Lets the development-only Django admin recognise the Admin role."""
        return self.role == Role.ADMIN

    @cached_property
    def teacher_profile(self):
        return (
            TeacherProfile.objects.select_related("registry", "hod_department")
            .filter(registry__claimed_by=self)
            .first()
        )

    @property
    def is_hod(self) -> bool:
        profile = self.teacher_profile
        return self.role == Role.TEACHER and profile is not None and profile.is_hod

    @property
    def hod_department(self):
        return self.teacher_profile.hod_department if self.is_hod else None

    @property
    def hod_department_id(self) -> int | None:
        return self.teacher_profile.hod_department_id if self.is_hod else None

    def refresh_from_db(self, *args, **kwargs):
        super().refresh_from_db(*args, **kwargs)
        self.__dict__.pop("teacher_profile", None)
        self._saved_username = self.username

    def save(self, *args, **kwargs):
        if self._saved_username is not None and self.username != self._saved_username:
            raise ValueError("A username is issued once and never changes.")
        self.contact_email_index = blind_index(self.contact_email, EMAIL_INDEX_PURPOSE)
        if self.contact_phone:
            self.contact_phone = normalize_phone(self.contact_phone)
        self.contact_phone_index = blind_index(self.contact_phone, PHONE_INDEX_PURPOSE)
        update_fields = kwargs.get("update_fields")
        if update_fields is not None:
            fields = set(update_fields)
            if "contact_email" in fields:
                fields.add("contact_email_index")
            if "contact_phone" in fields:
                fields.add("contact_phone_index")
            kwargs["update_fields"] = fields
        super().save(*args, **kwargs)
        self._saved_username = self.username


class IdType(models.TextChoices):
    STUDENT = "student", _("Student")
    TEACHER = "teacher", _("Teacher")


class RegistryStatus(models.TextChoices):
    UNCLAIMED = "unclaimed", _("Unclaimed")
    CLAIMED = "claimed", _("Claimed")
    REVOKED = "revoked", _("Revoked")


def registry_index(external_id: str) -> str:
    """Blind index of an ID in its canonical form (equality lookup and uniqueness)."""
    return blind_index(normalize_registry_id(external_id), REGISTRY_INDEX_PURPOSE)


class IdRegistry(models.Model):
    """A student or teacher ID the admin pre-registered; the account claims it at signup."""

    id_type = models.CharField(_("type"), max_length=16, choices=IdType.choices)
    external_id = EncryptedCharField(_("ID"), max_length=32)
    external_id_index = models.CharField(max_length=64, editable=False)
    full_name = EncryptedCharField(_("full name"), max_length=150, null=True, blank=True)
    department = models.ForeignKey(
        "academics.Department",
        on_delete=models.PROTECT,
        related_name="registry_entries",
        verbose_name=_("department"),
    )
    status = models.CharField(
        _("status"), max_length=16, choices=RegistryStatus.choices, default=RegistryStatus.UNCLAIMED
    )
    claimed_by = models.OneToOneField(
        User,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="registry",
        verbose_name=_("claimed by"),
    )
    activation_code_hash = models.CharField(max_length=64, blank=True, editable=False)
    activation_expires_at = models.DateTimeField(null=True, blank=True, editable=False)
    activation_used_at = models.DateTimeField(null=True, blank=True, editable=False)
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        verbose_name = _("ID registry entry")
        verbose_name_plural = _("ID registry")
        constraints = [
            models.UniqueConstraint(
                fields=["id_type", "external_id_index"], name="registry_unique_id_per_type"
            ),
            # Claimed needs an account and unclaimed has none. Revoked keeps whichever it had,
            # so re-activating restores the previous state.
            models.CheckConstraint(
                condition=models.Q(
                    claimed_by__isnull=False,
                    status__in=[RegistryStatus.CLAIMED, RegistryStatus.REVOKED],
                )
                | models.Q(
                    claimed_by__isnull=True,
                    status__in=[RegistryStatus.UNCLAIMED, RegistryStatus.REVOKED],
                ),
                name="registry_status_matches_claim",
            ),
        ]

    def __str__(self):
        return f"IdRegistry({self.pk})"

    def save(self, *args, **kwargs):
        self.external_id = normalize_registry_id(self.external_id)
        self.external_id_index = registry_index(self.external_id)
        update_fields = kwargs.get("update_fields")
        if update_fields is not None and "external_id" in update_fields:
            kwargs["update_fields"] = {*update_fields, "external_id_index"}
        super().save(*args, **kwargs)

    @property
    def activation_state(self) -> str:
        """``none``, ``active``, ``expired`` or ``used``: what the admin sees in the list."""
        if self.activation_used_at:
            return "used"
        if not self.activation_code_hash:
            return "none"
        if self.activation_expires_at and self.activation_expires_at <= timezone.now():
            return "expired"
        return "active"


class AcademicStatus(models.TextChoices):
    ACTIVE = "active", _("Active")
    GRADUATED = "graduated", _("Graduated")
    DROPPED = "dropped", _("Dropped")


class StudentProfile(models.Model):
    registry = models.OneToOneField(
        IdRegistry,
        on_delete=models.PROTECT,
        related_name="student_profile",
        verbose_name=_("registry entry"),
    )
    program = models.ForeignKey(
        "academics.Program",
        on_delete=models.PROTECT,
        related_name="students",
        verbose_name=_("program"),
    )
    batch = models.ForeignKey(
        "academics.Batch",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="students",
        verbose_name=_("batch"),
    )
    level_term = models.ForeignKey(
        "academics.LevelTerm",
        on_delete=models.PROTECT,
        related_name="students",
        verbose_name=_("level/term"),
    )
    section = models.CharField(_("section"), max_length=16, blank=True)
    academic_status = models.CharField(
        _("academic status"),
        max_length=16,
        choices=AcademicStatus.choices,
        default=AcademicStatus.ACTIVE,
    )

    class Meta:
        verbose_name = _("student profile")
        verbose_name_plural = _("student profiles")

    def __str__(self):
        return f"StudentProfile({self.pk})"


class TeacherProfile(models.Model):
    registry = models.OneToOneField(
        IdRegistry,
        on_delete=models.PROTECT,
        related_name="teacher_profile",
        verbose_name=_("registry entry"),
    )
    designation = models.CharField(_("designation"), max_length=100, blank=True)
    photo = models.ImageField(_("photo"), upload_to="teachers/", blank=True)
    is_hod = models.BooleanField(_("head of department"), default=False)
    hod_department = models.ForeignKey(
        "academics.Department",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="hod_profiles",
        verbose_name=_("department headed"),
    )

    class Meta:
        verbose_name = _("teacher profile")
        verbose_name_plural = _("teacher profiles")
        constraints = [
            models.UniqueConstraint(
                fields=["hod_department"],
                condition=models.Q(is_hod=True),
                name="one_hod_per_department",
            ),
            models.CheckConstraint(
                condition=models.Q(is_hod=True, hod_department__isnull=False)
                | models.Q(is_hod=False, hod_department__isnull=True),
                name="hod_flag_matches_department",
            ),
        ]

    def __str__(self):
        return f"TeacherProfile({self.pk})"
