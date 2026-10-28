from django.urls import path

from apps.feedback.student_views import dashboard as student_dashboard
from apps.reports.admin_views import home as admin_dashboard
from apps.reports.hod_views import overview as hod_dashboard
from apps.reports.views import dashboard as teacher_dashboard

from .views import account, auth, dashboards, profile, recovery, registry, signup, twofactor, users

app_name = "accounts"

urlpatterns = [
    path("login/", auth.login_view, name="login"),
    path("login/verify/", auth.login_second_factor, name="login_second_factor"),
    path("login/setup/", twofactor.login_two_factor_setup, name="login_two_factor_setup"),
    path("logout/", auth.logout_view, name="logout"),
    path("signup/", signup.signup_claim, name="signup"),
    path("signup/password/", signup.signup_password, name="signup_password"),
    path("signup/authenticator/", signup.signup_authenticator, name="signup_authenticator"),
    path("password/forgot/", recovery.password_forgot, name="password_forgot"),
    path("password/forgot/new/", recovery.password_forgot_new, name="password_forgot_new"),
    path("username/forgot/", recovery.username_forgot, name="username_forgot"),
    path("dashboard/", dashboards.dashboard, name="dashboard"),
    path("dashboard/student/", student_dashboard, name="dashboard_student"),
    path("dashboard/teacher/", teacher_dashboard, name="dashboard_teacher"),
    path("dashboard/hod/", hod_dashboard, name="dashboard_hod"),
    path("dashboard/admin/", admin_dashboard, name="dashboard_admin"),
    path("account/", account.account_home, name="account"),
    path("account/profile/", profile.profile_edit, name="profile"),
    path("account/password/", account.password_change, name="password_change"),
    path("account/sessions/end/", account.sign_out_everywhere, name="sign_out_everywhere"),
    path("account/2fa/", twofactor.two_factor, name="two_factor"),
    path("account/2fa/recovery/", twofactor.two_factor_regenerate, name="two_factor_regenerate"),
    path("account/2fa/device/", twofactor.two_factor_device, name="two_factor_device"),
    path(
        "account/2fa/device/confirm/",
        twofactor.two_factor_device_confirm,
        name="two_factor_device_confirm",
    ),
    path("manage/registry/", registry.registry_list, name="registry_list"),
    path("manage/registry/bulk/", registry.registry_bulk, name="registry_bulk"),
    path("manage/registry/new/<str:id_type>/", registry.registry_create, name="registry_create"),
    path("manage/registry/<int:pk>/", registry.registry_edit, name="registry_edit"),
    path("manage/registry/<int:pk>/hod/", registry.registry_hod, name="registry_hod"),
    path("manage/users/", users.user_list, name="user_list"),
    path("manage/users/<int:pk>/", users.user_detail, name="user_detail"),
    path("manage/users/<int:pk>/role/", users.user_role, name="user_role"),
    path("manage/users/<int:pk>/reset/", users.user_reset_access, name="user_reset_access"),
]
