from django.urls import path

from apps.feedback.student_views import dashboard as student_dashboard
from apps.reports.admin_views import home as admin_dashboard
from apps.reports.hod_views import overview as hod_dashboard

from .views import account, auth, dashboards, profile, recovery, registry, signup, twofactor, users

app_name = "accounts"

urlpatterns = [
    path("login/", auth.login_view, name="login"),
    path("login/verify/", auth.login_second_factor, name="login_second_factor"),
    path("login/setup/", twofactor.login_two_factor_setup, name="login_two_factor_setup"),
    path("logout/", auth.logout_view, name="logout"),
    path("signup/", signup.signup_claim, name="signup"),
    path("signup/contact/", signup.signup_contact, name="signup_contact"),
    path("signup/verify/", signup.signup_verify, name="signup_verify"),
    path("signup/resend/", signup.signup_resend, name="signup_resend"),
    path("signup/password/", signup.signup_password, name="signup_password"),
    path("password/forgot/", recovery.password_forgot, name="password_forgot"),
    path("password/forgot/verify/", recovery.password_forgot_verify, name="password_forgot_verify"),
    path("password/forgot/resend/", recovery.password_forgot_resend, name="password_forgot_resend"),
    path("password/forgot/new/", recovery.password_forgot_new, name="password_forgot_new"),
    path("username/forgot/", recovery.username_forgot, name="username_forgot"),
    path("username/forgot/verify/", recovery.username_forgot_verify, name="username_forgot_verify"),
    path("username/forgot/resend/", recovery.username_forgot_resend, name="username_forgot_resend"),
    path("dashboard/", dashboards.dashboard, name="dashboard"),
    path("dashboard/student/", student_dashboard, name="dashboard_student"),
    path("dashboard/teacher/", dashboards.dashboard_teacher, name="dashboard_teacher"),
    path("dashboard/hod/", hod_dashboard, name="dashboard_hod"),
    path("dashboard/admin/", admin_dashboard, name="dashboard_admin"),
    path("account/", account.account_home, name="account"),
    path("account/profile/", profile.profile_edit, name="profile"),
    path("account/password/", account.password_change, name="password_change"),
    path("account/sessions/end/", account.sign_out_everywhere, name="sign_out_everywhere"),
    path("account/2fa/", twofactor.two_factor, name="two_factor"),
    path("account/2fa/setup/", twofactor.account_two_factor_setup, name="two_factor_setup"),
    path("account/2fa/recovery/", twofactor.two_factor_regenerate, name="two_factor_regenerate"),
    path("account/2fa/disable/", twofactor.two_factor_disable, name="two_factor_disable"),
    path("manage/registry/", registry.registry_list, name="registry_list"),
    path("manage/registry/bulk/", registry.registry_bulk, name="registry_bulk"),
    path("manage/registry/new/<str:id_type>/", registry.registry_create, name="registry_create"),
    path("manage/registry/<int:pk>/", registry.registry_edit, name="registry_edit"),
    path("manage/registry/<int:pk>/hod/", registry.registry_hod, name="registry_hod"),
    path("manage/users/", users.user_list, name="user_list"),
    path("manage/users/<int:pk>/", users.user_detail, name="user_detail"),
    path("manage/users/<int:pk>/role/", users.user_role, name="user_role"),
]
